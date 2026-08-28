import type { Catalog, CompanionState, PersonaSpec } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status code */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const fetchCatalog = () => fetch("/api/catalog").then(json<Catalog>);

export const fetchCompanion = () => fetch("/api/companion").then(json<CompanionState>);

export function createCompanion(spec: PersonaSpec, reset = false) {
  return fetch("/api/companion", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...spec, reset }),
  }).then(json<{ ok: boolean; first_message: string | null }>);
}

export const fetchResponseLength = () =>
  fetch("/companion/response_length").then(json<{ level: number }>);

export const setResponseLength = (level: number) =>
  fetch("/companion/response_length", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level }),
  }).then(json<{ level: number }>);
