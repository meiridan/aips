import { describe, expect, it } from "vitest";

import {
  isEmpty,
  validateEmail,
  validateLogin,
  validatePassword,
  validateReset,
  validateSignup,
} from "../validation";

describe("validateEmail", () => {
  it.each(["a@b.co", "ada.lovelace@example.com", "x+tag@mail.example.co.uk"])(
    "accepts %s",
    (email) => {
      expect(validateEmail(email)).toBeNull();
    },
  );

  it("trims before judging", () => {
    expect(validateEmail("  a@b.co  ")).toBeNull();
  });

  it("requires a value", () => {
    expect(validateEmail("")).toBe("email_required");
    expect(validateEmail("   ")).toBe("email_required");
  });

  it.each(["nope", "a@b", "a b@c.co", "@b.co", "a@.co", "a@b."])("rejects %s", (email) => {
    expect(validateEmail(email)).toBe("email_invalid");
  });

  it("rejects an absurdly long address", () => {
    expect(validateEmail(`${"x".repeat(250)}@b.co`)).toBe("email_invalid");
  });
});

describe("validatePassword", () => {
  it("accepts eight characters or more", () => {
    expect(validatePassword("12345678")).toBeNull();
  });

  it("rejects short and empty", () => {
    expect(validatePassword("")).toBe("password_required");
    expect(validatePassword("1234567")).toBe("password_too_short");
  });

  it("rejects an unbounded password", () => {
    expect(validatePassword("x".repeat(201))).toBe("password_too_long");
  });
});

describe("validateLogin", () => {
  it("passes a filled form", () => {
    expect(isEmpty(validateLogin("a@b.co", "anything"))).toBe(true);
  });

  it("does not apply the length rule to an existing password", () => {
    // Telling someone their current password is 'too short' would be wrong,
    // and would leak the current policy to whoever is guessing.
    expect(validateLogin("a@b.co", "old")).toEqual({});
  });

  it("reports both fields at once", () => {
    expect(validateLogin("", "")).toEqual({
      email: "email_required",
      password: "password_required",
    });
  });
});

describe("validateSignup", () => {
  it("does apply the length rule", () => {
    expect(validateSignup("a@b.co", "short")).toEqual({ password: "password_too_short" });
  });

  it("passes a good pair", () => {
    expect(isEmpty(validateSignup("a@b.co", "long-enough"))).toBe(true);
  });
});

describe("validateReset", () => {
  it("requires the two entries to match", () => {
    expect(validateReset("long-enough", "long-enougi")).toEqual({
      confirm: "password_mismatch",
    });
  });

  it("reports weakness before mismatch", () => {
    expect(validateReset("short", "other")).toEqual({ password: "password_too_short" });
  });

  it("passes a matching, strong pair", () => {
    expect(isEmpty(validateReset("long-enough", "long-enough"))).toBe(true);
  });
});
