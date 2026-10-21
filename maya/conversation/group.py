"""Group chat: one user message, several companions (§ group chat).

The 1:1 orchestrator answers with one voice. Here a room holds the account's
own companion and a partner (Lila), and one user message runs a small floor
plan:

1. Route: who was spoken to (`addressing.resolve_addressees`).
2. Save the user turn, gather each addressee's context in parallel — the same
   services the 1:1 path uses, so Maya is the same Maya in both rooms.
3. Speak in order, one main-tier call per speaker, *sequentially*: the second
   speaker's prompt already holds the first one's reply, so they talk to each
   other rather than past each other.
4. Continue, by the room's talk mode (`group_settings`): in "moderated" they go
   back and forth until `min_ai_messages`, then a cheap director call decides
   whether someone adds one more, up to `max_ai_messages`; in "free" they keep
   alternating until the user writes or `free_talk_max_messages`. The mode is
   re-read before every speaker, so switching it mid-turn takes effect at once.
   No speaker twice in a row, and a near-repeat ends the turn.
5. `turn_end` goes out, then post-processing is awaited (Decision 2, as in the
   1:1 path: the reply is out first, bookkeeping never detached).

A new user message sets `cancel`: the speaker mid-stream finishes, nobody new
starts.
"""

from __future__ import annotations

import asyncio
import difflib
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from maya.companions import catalog
from maya.companions.templates import get_template
from maya.config import get_settings
from maya.conversation import prompt_log, response_length, rooms
from maya.conversation.addressing import resolve_addressees
from maya.conversation.director import Candidate, Director
from maya.conversation.group_settings import GroupSettings
from maya.conversation.moment_analyzer import MomentAnalysis, default_moment
from maya.conversation.orchestrator import (
    MEMORY_LIMIT,
    RECENT_LIMIT,
    SIGNIFICANT_INTENSITY,
    Orchestrator,
    StepCallback,
    _emit,
)
from maya.conversation.prompt_builder import (
    GroupLine,
    OtherMember,
    build_group_phase3,
    count_tokens,
)
from maya.conversation.reply_guard import ReplyGuard
from maya.db.models import Message
from maya.logging import get_logger

log = get_logger("maya.group")

#: Sends one protocol event to the channel (see the /ws/group handler).
Emit = Callable[[dict[str, Any]], Awaitable[None]]

# A follow-up this close to something already said this turn is a loop, not a
# conversation — stop there.
_REPEAT_RATIO = 0.9


@dataclass
class _SpeakerCtx:
    companion: Any
    memories: list[dict[str, Any]]
    emotional: Any
    relationship: Any
    commitments: list[Any]


@dataclass(frozen=True)
class PromptPreview:
    """What `preview_prompt` found — the prompt plus the context it came from."""

    prompt: list[dict[str, str]]
    companion: Any
    memories: list[dict[str, Any]]
    emotional: Any
    relationship: Any
    commitments: list[Any]
    user_name: str
    addressed: list[str]
    turn_note: str
    recent_turns: int


@dataclass(frozen=True)
class SpokenLine:
    member: rooms.Member
    content: str
    message_id: uuid.UUID


class GroupOrchestrator:
    def __init__(
        self,
        orchestrator: Orchestrator,
        director: Director | None = None,
        *,
        max_ai_messages: int | None = None,
        min_ai_messages: int | None = None,
        free_talk_max_messages: int | None = None,
        director_enabled: bool | None = None,
    ) -> None:
        settings = get_settings()
        self.orch = orchestrator
        self.director = director or Director(orchestrator.llm)
        self.max_ai_messages = max(
            1,
            max_ai_messages
            if max_ai_messages is not None
            else settings.group_max_ai_messages_per_turn,
        )
        self.min_ai_messages = min(
            self.max_ai_messages,
            max(
                1,
                min_ai_messages
                if min_ai_messages is not None
                else settings.group_moderated_min_messages,
            ),
        )
        self.free_talk_max_messages = max(
            1,
            free_talk_max_messages
            if free_talk_max_messages is not None
            else settings.group_free_talk_max_messages,
        )
        self.director_enabled = (
            director_enabled if director_enabled is not None else settings.group_director_enabled
        )

    async def run_turn(
        self,
        room: rooms.GroupRoom,
        content: str,
        *,
        emit: Emit,
        target: str | None = None,
        cancel: asyncio.Event | None = None,
        settings: GroupSettings | None = None,
        on_step: StepCallback | None = None,
    ) -> list[SpokenLine]:
        """Handle one user message in `room`. Returns what the companions said.

        `settings` may be changed by the caller while the turn runs (the socket
        shares its live object); without it the room's stored settings apply.
        """
        if not room.members:
            raise ValueError(f"group room {room.conversation_id} has no members")
        talk = settings if settings is not None else GroupSettings.from_dict(room.settings)
        turn_id = uuid.uuid4().hex[:8]
        sm = self.orch._sessionmaker

        addressees = resolve_addressees(content, [m.addressable() for m in room.members], target)
        addressed = [m for cid in addressees if (m := room.member(cid)) is not None]
        addressed_slots = [m.slot for m in addressed]
        await emit({"type": "turn_start", "addressed": addressed_slots})
        await _emit(
            on_step,
            "step",
            f"🎯 Addressed: {', '.join(addressed_slots)}",
            {
                "content": content[:100],
                "target": target,
                **talk.as_dict(),
            },
        )

        # Saved first, so the transcript read below is guaranteed to hold it.
        async with sm() as session:
            await self.orch._save_message(
                session,
                None,
                room.user_id,
                "user",
                content,
                conversation_id=room.conversation_id,
                extra={"addressed": addressed_slots},
            )
            await session.commit()

        member_ids = [m.companion_id for m in room.members]
        # Separate tasks rather than one mixed gather, so each result keeps its type.
        name_task = asyncio.create_task(self.orch._user_name(room.user_id))
        transcript_task = asyncio.create_task(
            rooms.load_transcript(sm, room.conversation_id, RECENT_LIMIT)
        )
        loaded = await asyncio.gather(*(self.orch._load_companion(cid) for cid in member_ids))
        user_name, transcript = await name_task, await transcript_task
        companions = dict(zip(member_ids, loaded, strict=True))
        lines = [self._line(msg, room, user_name) for msg in transcript]

        ctxs: dict[uuid.UUID, _SpeakerCtx] = {}
        await self._gather_contexts(ctxs, addressed, companions, content, room.user_id)
        first = ctxs[addressed[0].companion_id]
        moment_task = asyncio.create_task(
            self.orch.moment_analyzer.analyze(
                content, first.emotional, first.relationship, transcript
            )
        )

        spoken: list[SpokenLine] = []
        try:
            queue = self._speaking_order(room, addressed, transcript)
            last_slot: str | None = None
            # Set when the queued speaker is carrying on the back-and-forth,
            # rather than answering the user or being picked by the director.
            exchange = False
            while queue and len(spoken) < self._ceiling(talk):
                if cancel is not None and cancel.is_set():
                    await _emit(on_step, "step", "✋ Interrupted by a new message", {})
                    break
                member = queue.pop(0)
                if member.slot == last_slot:
                    continue
                await self._gather_contexts(ctxs, [member], companions, content, room.user_id)
                line = await self._speak(
                    turn_id=turn_id,
                    room=room,
                    member=member,
                    ctx=ctxs[member.companion_id],
                    companions=companions,
                    lines=lines,
                    user_name=user_name,
                    addressed=addressed,
                    spoken=spoken,
                    talk=talk,
                    exchange=exchange,
                    emit=emit,
                    on_step=on_step,
                )
                if line is None:
                    continue
                repeated = self._repeats(line.content, spoken)
                spoken.append(line)
                lines.append(GroupLine(member.companion_id, member.name, line.content))
                last_slot = member.slot
                if repeated:
                    await _emit(on_step, "step", "🔁 Near-repeat — ending the turn", {})
                    break

                if (
                    not queue
                    and len(room.members) > 1
                    and len(spoken) < self._ceiling(talk)
                    and not (cancel is not None and cancel.is_set())
                ):
                    follow, exchange = await self._follow_up(
                        room=room,
                        talk=talk,
                        spoken=spoken,
                        lines=lines,
                        last_slot=last_slot,
                        user_name=user_name,
                        addressed_slots=addressed_slots,
                        on_step=on_step,
                    )
                    if follow is not None:
                        queue.append(follow)
            if talk.free and len(spoken) >= self._ceiling(talk):
                await _emit(on_step, "step", "⏸️ Free talk paused at the safety limit", {})
        except BaseException:
            moment_task.cancel()
            raise
        finally:
            await emit({"type": "turn_end"})

        moment = await moment_task
        await self._post_process(
            room=room,
            content=content,
            addressed=addressed,
            spoken=spoken,
            moment=moment,
            on_step=on_step,
        )
        await _emit(on_step, "step", "🎉 Group turn complete", {"messages": len(spoken)})
        return spoken

    # ── one speaker ──────────────────────────────────────────────────────

    async def _speak(
        self,
        *,
        turn_id: str,
        room: rooms.GroupRoom,
        member: rooms.Member,
        ctx: _SpeakerCtx,
        companions: dict[uuid.UUID, Any],
        lines: list[GroupLine],
        user_name: str,
        addressed: Sequence[rooms.Member],
        spoken: Sequence[SpokenLine],
        talk: GroupSettings,
        exchange: bool,
        emit: Emit,
        on_step: StepCallback | None,
    ) -> SpokenLine | None:
        others = [m for m in room.members if m.companion_id != member.companion_id]
        level = talk.response_length
        prompt = self._build_prompt(
            room=room,
            member=member,
            ctx=ctx,
            companions=companions,
            lines=lines,
            user_name=user_name,
            addressed=addressed,
            spoken=spoken,
            level=level,
            exchange=exchange,
        )

        speaker_turn = f"{turn_id}-{member.slot}"
        if prompt_log.log_path() is not None:
            prompt_log.record_prompt(
                turn_id=speaker_turn,
                companion_name=member.name,
                prompt=prompt,
                tokens=count_tokens(prompt[0]["content"]),
            )

        await emit({"type": "message_start", "speaker": member.slot})
        await _emit(on_step, "llm", f"🤖 {member.name} is answering", {"messages": len(prompt)})
        guard = ReplyGuard(member.name, [m.name for m in others] + [user_name])
        parts: list[str] = []
        stream = self.orch.llm.chat_stream(
            prompt,
            model_tier=self.orch._default_tier,
            max_tokens=response_length.group_max_tokens_for(level),
            purpose="group_reply",
        )
        try:
            async for piece in stream:
                safe = guard.feed(piece)
                if safe:
                    parts.append(safe)
                    await emit({"type": "message_chunk", "speaker": member.slot, "content": safe})
                if guard.stopped:
                    await _emit(
                        on_step, "step", f"✂️ Cut {member.name} speaking for someone else", {}
                    )
                    break
            tail = guard.finish()
            if tail:
                parts.append(tail)
                await emit({"type": "message_chunk", "speaker": member.slot, "content": tail})
        except Exception as exc:  # noqa: BLE001 - one speaker failing must not end the room
            log.error("group_speaker_failed", speaker=member.slot, error=str(exc))
            await _emit(on_step, "error", f"❌ {member.name}: {type(exc).__name__}: {exc}", {})
            await emit({"type": "message_end", "speaker": member.slot})
            return None
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

        await emit({"type": "message_end", "speaker": member.slot})
        reply = "".join(parts).strip()
        if not reply:
            return None

        async with self.orch._sessionmaker() as session:
            msg: Message = await self.orch._save_message(
                session,
                member.companion_id,
                room.user_id,
                "assistant",
                reply,
                conversation_id=room.conversation_id,
                extra={"speaker": member.slot, "turn": turn_id},
            )
            message_id = msg.id
            await session.commit()
        prompt_log.record_reply(turn_id=speaker_turn, reply=reply)
        return SpokenLine(member=member, content=reply, message_id=message_id)

    def _build_prompt(
        self,
        *,
        room: rooms.GroupRoom,
        member: rooms.Member,
        ctx: _SpeakerCtx,
        companions: dict[uuid.UUID, Any],
        lines: list[GroupLine],
        user_name: str,
        addressed: Sequence[rooms.Member],
        spoken: Sequence[SpokenLine],
        level: int,
        exchange: bool = False,
        enforce_budget: bool = True,
    ) -> list[dict[str, str]]:
        others = [m for m in room.members if m.companion_id != member.companion_id]
        prompt = build_group_phase3(
            companion=ctx.companion,
            others=[_other(m, companions.get(m.companion_id)) for m in others],
            room_dynamics=self._dynamics(room, user_name),
            memories=ctx.memories,
            emotional=ctx.emotional,
            relationship=ctx.relationship,
            commitments=ctx.commitments,
            moment=default_moment(),
            lines=lines,
            user_name=user_name,
            turn_note=_turn_note(member, addressed, spoken, user_name, exchange=exchange),
            hours_since_last=Orchestrator._hours_since(
                getattr(ctx.relationship, "last_interaction_at", None)
            ),
            response_length=level,
            enforce_budget=enforce_budget,
        )
        if prompt[-1]["role"] != "user":
            # Only reachable if her own line closes the transcript; the model
            # still needs a turn to answer.
            prompt.append({"role": "user", "content": f"[{user_name}]: …"})
        return prompt

    async def preview_prompt(
        self,
        room: rooms.GroupRoom,
        member: rooms.Member,
        content: str,
        *,
        target: str | None = None,
        search_memory: bool = True,
    ) -> PromptPreview:
        """The prompt `member` would open this turn with if `content` were sent
        now. Writes nothing — this backs `maya show-prompt --group`."""
        addressees = resolve_addressees(content, [m.addressable() for m in room.members], target)
        addressed = [m for cid in addressees if (m := room.member(cid)) is not None]
        member_ids = [m.companion_id for m in room.members]
        loaded = await asyncio.gather(*(self.orch._load_companion(cid) for cid in member_ids))
        companions = dict(zip(member_ids, loaded, strict=True))
        user_name = await self.orch._user_name(room.user_id)
        transcript = await rooms.load_transcript(
            self.orch._sessionmaker, room.conversation_id, RECENT_LIMIT
        )
        lines = [self._line(msg, room, user_name) for msg in transcript]
        lines.append(GroupLine(None, user_name, content))

        ctxs: dict[uuid.UUID, _SpeakerCtx] = {}
        await self._gather_contexts(
            ctxs, [member], companions, content, room.user_id, search_memory=search_memory
        )
        ctx = ctxs[member.companion_id]
        prompt = self._build_prompt(
            room=room,
            member=member,
            ctx=ctx,
            companions=companions,
            lines=lines,
            user_name=user_name,
            addressed=addressed,
            spoken=[],
            level=GroupSettings.from_dict(room.settings).response_length,
            enforce_budget=False,  # over budget is exactly when you need to look
        )
        return PromptPreview(
            prompt=prompt,
            companion=ctx.companion,
            memories=ctx.memories,
            emotional=ctx.emotional,
            relationship=ctx.relationship,
            commitments=ctx.commitments,
            user_name=user_name,
            addressed=[m.slot for m in addressed],
            turn_note=_turn_note(member, addressed, [], user_name),
            recent_turns=len(transcript),
        )

    # ── helpers ──────────────────────────────────────────────────────────

    async def _gather_contexts(
        self,
        ctxs: dict[uuid.UUID, _SpeakerCtx],
        members: Sequence[rooms.Member],
        companions: dict[uuid.UUID, Any],
        content: str,
        user_id: uuid.UUID,
        *,
        search_memory: bool = True,
    ) -> None:
        """Fill `ctxs` for any member who has none yet, all in one gather."""

        async def one(member: rooms.Member) -> None:
            companion = companions.get(member.companion_id)
            baseline = get_template(companion.template_id).baseline_emotional if companion else {}
            memories, emotional, relationship, commitments = await asyncio.gather(
                (
                    self.orch.memory.search_relevant(
                        content, user_id, member.companion_id, MEMORY_LIMIT
                    )
                    if search_memory
                    else _no_memories()
                ),
                self.orch.emotional.get(member.companion_id, baseline=baseline),
                self.orch.relationship.get(member.companion_id, user_id),
                self.orch.commitments.get_recent(member.companion_id, limit=20),
            )
            ctxs[member.companion_id] = _SpeakerCtx(
                companion=companion,
                memories=memories,
                emotional=emotional,
                relationship=relationship,
                commitments=commitments,
            )

        await asyncio.gather(*(one(m) for m in members if m.companion_id not in ctxs))

    @staticmethod
    def _line(msg: Message, room: rooms.GroupRoom, user_name: str) -> GroupLine:
        if msg.role == "user":
            return GroupLine(None, user_name, msg.content)
        member = room.member(msg.companion_id)
        return GroupLine(msg.companion_id, member.name if member else "?", msg.content)

    @staticmethod
    def _speaking_order(
        room: rooms.GroupRoom,
        addressed: Sequence[rooms.Member],
        transcript: Sequence[Message],
    ) -> list[rooms.Member]:
        """Named order when the user named them; otherwise whoever spoke last
        opens, so the opener alternates instead of always being the same one."""
        order = list(addressed)
        seat_order = [m.companion_id for m in room.members]
        if len(order) < 2 or [m.companion_id for m in order] != seat_order:
            return order
        last = next((m.companion_id for m in reversed(transcript) if m.role == "assistant"), None)
        return [m for m in order if m.companion_id == last] + [
            m for m in order if m.companion_id != last
        ]

    def _ceiling(self, talk: GroupSettings) -> int:
        """Most companion lines this turn — read per speaker, so a toggle bites mid-turn."""
        return self.free_talk_max_messages if talk.free else self.max_ai_messages

    async def _follow_up(
        self,
        *,
        room: rooms.GroupRoom,
        talk: GroupSettings,
        spoken: Sequence[SpokenLine],
        lines: Sequence[GroupLine],
        last_slot: str | None,
        user_name: str,
        addressed_slots: Sequence[str],
        on_step: StepCallback | None,
    ) -> tuple[rooms.Member | None, bool]:
        """Who speaks after the planned speakers, and whether that is the
        back-and-forth carrying on. `(None, False)` hands the floor back.

        Free talk, and a moderated turn short of its minimum, keep the two of
        them going — no director call. Past the minimum the director decides.
        """
        if talk.free or len(spoken) < self.min_ai_messages:
            nxt = self._next_seat(room, last_slot)
            await _emit(on_step, "step", f"🔄 Back and forth → {nxt.slot}", {})
            return nxt, True
        if not self.director_enabled:
            return None, False
        slot = await self.director.next_speaker(
            transcript=[(ln.name, ln.content) for ln in lines],
            members=[Candidate(m.slot, m.name) for m in room.members],
            last_slot=last_slot,
            user_name=user_name,
            addressed_slots=addressed_slots,
        )
        await _emit(on_step, "step", f"🎬 Director → {slot or 'end'}", {})
        return (room.by_slot(slot) if slot else None), False

    @staticmethod
    def _next_seat(room: rooms.GroupRoom, last_slot: str | None) -> rooms.Member:
        """The member seated after whoever spoke last."""
        slots = [m.slot for m in room.members]
        i = slots.index(last_slot) if last_slot in slots else -1
        return room.members[(i + 1) % len(room.members)]

    @staticmethod
    def _repeats(text: str, spoken: Sequence[SpokenLine]) -> bool:
        return any(
            difflib.SequenceMatcher(None, text, line.content).ratio() >= _REPEAT_RATIO
            for line in spoken
        )

    @staticmethod
    def _dynamics(room: rooms.GroupRoom, user_name: str) -> str:
        primary = next((m for m in room.members if m.slot == rooms.SLOT_PRIMARY), None)
        partner = next((m for m in room.members if m.slot != rooms.SLOT_PRIMARY), None)
        return catalog.fill_names(
            str(room.dynamics.get("description", "")),
            primary=primary.name if primary else "",
            partner=partner.name if partner else "",
            user=user_name,
        )

    async def _post_process(
        self,
        *,
        room: rooms.GroupRoom,
        content: str,
        addressed: Sequence[rooms.Member],
        spoken: Sequence[SpokenLine],
        moment: MomentAnalysis,
        on_step: StepCallback | None,
    ) -> None:
        """Every store, after the turn is already on screen.

        - memory: everyone in the room heard the user, so his facts go into each
          member's (user, companion) scope — not just the addressees'.
        - emotions and the significant-event log: the addressees, whom the
          message was actually for.
        - relationship: anyone who was addressed or spoke.
        - commitments: each companion from her own lines only.
        """
        orch = self.orch
        addressed_ids = {m.companion_id for m in addressed}
        involved = addressed_ids | {line.member.companion_id for line in spoken}
        tasks: list[Awaitable[Any]] = [
            orch.memory.extract_and_store(
                user_id=room.user_id,
                companion_id=m.companion_id,
                user_message=content,
                assistant_message="",
            )
            for m in room.members
        ]
        tasks += [
            orch.emotional.update_after_message(cid, moment.emotional_delta)
            for cid in addressed_ids
        ]
        tasks += [orch.relationship.increment_interaction(cid) for cid in involved]
        tasks += [
            orch.commitments.extract_from_message(
                line.member.companion_id,
                line.member.name,
                line.content,
                source_message_id=line.message_id,
            )
            for line in spoken
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                log.warning("group_post_process_failed", error=str(result))

        for cid in involved:
            try:
                if cid in addressed_ids and moment.emotional_intensity > SIGNIFICANT_INTENSITY:
                    await orch.relationship.log_event(
                        companion_id=cid,
                        event_type="emotional_moment",
                        summary=f"Intense {moment.moment_type} (group chat)",
                        impact={"intimacy_delta": 1},
                    )
                new_stage = await orch.relationship.evaluate_stage_transition(cid)
                if new_stage is not None:
                    await _emit(
                        on_step,
                        "step",
                        f"💞 Stage → {new_stage.value}",
                        {
                            "companion_id": str(cid),
                            "stage": new_stage.value,
                        },
                    )
            except Exception as exc:  # noqa: BLE001 - bookkeeping must not break the room
                log.warning("group_relationship_update_failed", error=str(exc))


async def _no_memories() -> list[dict[str, Any]]:
    return []


def _other(member: rooms.Member, companion: Any) -> OtherMember:
    personality = getattr(companion, "personality", {}) or {}
    return OtherMember(
        name=member.name,
        description=str(personality.get("description") or ""),
        backstory=str(getattr(companion, "backstory", "") or ""),
    )


def _turn_note(
    member: rooms.Member,
    addressed: Sequence[rooms.Member],
    spoken: Sequence[SpokenLine],
    user_name: str,
    *,
    exchange: bool = False,
) -> str:
    """One line telling her why it is her turn — the part a transcript can't say."""
    already = [line for line in spoken if line.member.companion_id != member.companion_id]
    if exchange:
        names = " and ".join(dict.fromkeys(line.member.name for line in already)) or "the others"
        return (
            f"{user_name} is right here, but for the moment it is you and {names} going back "
            "and forth. React to what was just said and move the conversation forward — a new "
            "thought, a question, a tease, a turn — never recap or repeat what was already said."
        )
    if any(line.member.companion_id == member.companion_id for line in spoken):
        return (
            "You already spoke this turn. This is a quick follow-up to what was just said — "
            "don't repeat yourself."
        )
    if member in addressed and len(addressed) == 1:
        return f"{user_name}'s last message was to you alone — answer him."
    if member in addressed:
        note = f"{user_name}'s last message was to all of you."
        if already:
            names = " and ".join(dict.fromkeys(line.member.name for line in already))
            note += f" {names} already answered — build on it instead of repeating it."
        return note
    names = " and ".join(m.name for m in addressed) or "someone else"
    return (
        f"{user_name} was talking to {names}, not you. You are jumping in on your own — "
        "keep it short and make it count."
    )
