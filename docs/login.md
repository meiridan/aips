# Task: Plan Login & Subscription Screens

You are working on an existing application. Your task is to **analyze the current codebase and prepare a detailed implementation plan** for adding Login and Subscription screens.

## Important: Plan Mode Only

Do **not implement or modify any code yet**.

First inspect the existing application thoroughly and produce an implementation plan based on what is **already available in the project**.

Do not introduce a new frontend framework, backend framework, authentication library, UI library, state-management solution, database technology, or payment provider unless the existing application has no suitable solution and you explicitly explain why it is required.

---

## 1. Analyze the Existing Application

Before creating the plan, inspect:

### Frontend
Identify:

- Frontend framework and version
- Language
- Existing routing/navigation
- Existing UI/component library
- Existing styling approach
- Existing form components
- Existing validation framework
- Existing state management
- Existing API/client layer
- Existing authentication-related code
- Existing user/profile screens
- Existing loading/error/toast patterns
- Existing responsive/mobile behavior
- Existing design system/theme

### Backend
Identify:

- Backend framework and language
- Existing API architecture
- Existing user/account models
- Existing authentication mechanisms
- Existing session/token/JWT handling
- Existing password hashing
- Existing email infrastructure
- Existing database and schema
- Existing API error conventions
- Existing authorization middleware

### Existing Integrations

Look specifically for existing support for:

- Google/Gmail authentication
- OAuth / Google OAuth
- Email/password authentication
- Password reset
- Email verification
- Subscription management
- Payments
- Stripe or another payment provider
- Existing subscription/user entitlement models
- Webhooks
- Feature flags
- Environment/configuration management

Reuse existing capabilities wherever possible.

---

# 2. Login Screen Requirements

Plan a login experience supporting **two authentication methods**:

### Option A — Continue with Google

Provide a prominent:

**Continue with Google**

button.

Use the application's existing authentication/OAuth infrastructure if available.

If Google authentication does not currently exist, determine the minimum required implementation using the technologies already present in the application.

Do not assume a specific OAuth library before inspecting the project.

### Option B — Email + Password

Provide:

- Email
- Password
- Login button
- "Forgot password?"
- Link to Sign Up / Create Account

Expected behavior:

- Client-side validation using the existing validation mechanism
- Server-side validation
- Clear validation errors
- Clear authentication errors
- Loading state during authentication
- Prevent duplicate submissions
- Successful login redirects to the appropriate authenticated area
- Preserve the application's existing navigation/authentication conventions

---

# 3. Forgot Password

The email/password login flow must include:

**Forgot password?**

The plan should cover:

1. User enters email
2. Request password reset
3. Backend generates a secure reset mechanism
4. Reset email is sent
5. User follows reset link
6. User enters a new password
7. Password is securely updated
8. Reset token becomes invalid
9. User can log in with the new password

Use existing email infrastructure if available.

Important security requirements:

- Do not reveal whether an email address exists
- Reset tokens must be securely generated
- Reset tokens must expire
- Reset tokens must be single-use
- Do not store raw reset tokens if the existing architecture supports secure hashing
- Follow the application's existing security conventions

If any of these mechanisms already exist, reuse them rather than implementing duplicates.

---

# 4. Subscription Screen

Prepare a subscription/pricing screen that fits the application's existing UI and architecture.

First inspect whether subscription functionality already exists.

The screen should support:

- Displaying available subscription plans
- Plan name
- Price
- Billing period
- Main benefits/features
- Current user's subscription status
- Current plan indication
- Upgrade/downgrade actions where applicable
- Subscription state/loading/error handling

If a payment provider already exists, integrate with it using the existing implementation.

If no payment infrastructure exists, **do not automatically implement a payment provider**. Instead, identify what would be required and propose the minimal architecture in the plan.

---

# 5. Authentication States

The plan should cover the application's relevant states:

- Logged out
- Login in progress
- Login failed
- Logged in
- Session expired
- Password reset requested
- Password reset completed
- Authentication error
- Subscription loading
- Subscription loaded
- Subscription purchase/update in progress
- Subscription error

Reuse existing global authentication/session handling where possible.

---

# 6. Routing

Determine the existing routing architecture and propose routes appropriate for:

- Login
- Sign Up, if already supported or required by the existing architecture
- Forgot Password
- Reset Password
- Subscription / Pricing

Do not invent a routing system.

Use the existing router and routing conventions.

Also determine which routes should be:

- Public
- Authenticated-only

---

# 7. UX / UI

The screens should feel like a **native part of the existing application**, not a separate mini-application.

Inspect existing screens and identify:

- Typography
- Colors
- Spacing
- Buttons
- Cards
- Inputs
- Icons
- Modal/dialog patterns
- Responsive behavior
- Error messages
- Toasts/notifications

Reuse existing components wherever possible.

Do not introduce a new UI library just for these screens.

The Login screen should be simple and focused.

Suggested conceptual structure:

```text
Login
 ├── App branding
 ├── Continue with Google
 ├── Divider
 ├── Email
 ├── Password
 ├── Forgot password?
 ├── Login
 └── Don't have an account? Sign up
```

Subscription:

```text
Subscription
 ├── Current subscription status
 ├── Available plans
 │    ├── Plan
 │    ├── Price
 │    ├── Benefits
 │    └── Select/Upgrade button
 └── Existing subscription management
```

These are conceptual structures only. Adapt them to the application's existing design.

---

# 8. API / Backend Planning

Identify all required API changes.

For each API, specify:

- Endpoint
- HTTP method
- Request payload
- Response
- Authentication requirements
- Validation
- Error responses
- Relevant existing service/controller/model to reuse or extend

Potential functionality to evaluate:

```text
POST   /auth/login
POST   /auth/google
POST   /auth/forgot-password
POST   /auth/reset-password
GET    /subscription
GET    /subscription/plans
POST   /subscription/checkout
POST   /subscription/change
POST   /subscription/cancel
```

**Do not assume these exact endpoints should be created.**

First inspect the existing API architecture and determine whether equivalent endpoints already exist.

---

# 9. Database / Data Model

Inspect the existing database models.

Determine whether the application already has:

- Users
- Authentication providers
- Password credentials
- Password reset tokens
- Subscriptions
- Plans
- Payment/customer IDs
- Subscription status
- Subscription expiration/renewal information

Identify only the schema changes that are actually required.

Avoid duplicate models or fields.

---

# 10. Security

The implementation plan must explicitly address:

- Password hashing
- Authentication/session security
- Google OAuth security
- Password reset token security
- Token expiration
- Rate limiting/brute-force protection
- CSRF protection where relevant
- Secure cookies/storage
- Authorization
- Subscription entitlement validation
- Preventing client-side manipulation of subscription status

Use the existing application's security mechanisms whenever possible.

---

# 11. Testing Plan

Identify tests that should be added or updated.

### Frontend

Cover at minimum:

- Login rendering
- Google login interaction
- Email validation
- Password validation
- Failed login
- Successful login
- Forgot-password flow
- Reset-password flow
- Loading states
- Subscription rendering
- Current-plan state
- Upgrade/select-plan interaction
- Error states

### Backend

Cover:

- Valid login
- Invalid credentials
- Unknown user
- Google authentication
- Password reset request
- Invalid/expired reset token
- Successful password reset
- Subscription retrieval
- Subscription authorization
- Subscription changes/payment flow if applicable

Use the project's existing testing framework.

Do not introduce another testing framework.

---

# 12. Environment / Configuration

Inspect existing environment/configuration conventions.

Identify any new configuration required, such as:

- Google OAuth credentials
- Authentication secrets
- Password-reset URL
- Email configuration
- Payment provider configuration
- Webhook secrets

Do not expose secrets in source control.

Follow the application's existing `.env`, secrets, deployment, and configuration conventions.

---

# 13. Deliverable

After inspecting the repository, produce a **detailed implementation plan**, NOT code.

The plan must include:

### A. Current Architecture

Summarize:

- FE stack
- BE stack
- Authentication architecture
- Database
- Routing
- UI architecture
- Existing relevant components/services

### B. Existing Code to Reuse

List specific:

- Files
- Components
- Services
- Controllers
- Models
- Hooks
- Utilities
- APIs

Explain how each should be reused or extended.

### C. Required Changes

Organize by:

1. Frontend
2. Backend
3. Database
4. Authentication
5. Subscription
6. Routing
7. Configuration
8. Tests

### D. User Flows

Describe step-by-step:

- Google login
- Email/password login
- Forgot password
- Reset password
- Subscription selection
- Existing-user subscription management

### E. File-Level Plan

Provide the expected files to:

- Modify
- Create
- Delete, if any

For each file explain what changes are required.

### F. Dependencies

Clearly distinguish:

- Already installed dependencies that can be reused
- Dependencies that are missing but genuinely required

Avoid unnecessary dependencies.

### G. Risks / Questions

Identify anything discovered in the codebase that could affect the implementation.

Do not silently make architectural assumptions.

### H. Implementation Order

Provide a recommended step-by-step implementation sequence that minimizes risk and keeps the application buildable/testable throughout.

---

## Critical Rules

1. **Inspect before planning.**
2. **Reuse the existing FE and BE technology.**
3. **Reuse existing authentication infrastructure.**
4. **Reuse existing UI components and design system.**
5. **Do not introduce new frameworks without justification.**
6. **Do not implement anything while in Plan Mode.**
7. **Do not invent APIs, database models, or dependencies before inspecting the codebase.**
8. **Do not assume Stripe or Google OAuth libraries are present. Verify first.**
9. **Do not duplicate functionality that already exists.**
10. Prioritize a clean, production-ready architecture consistent with the existing application.
11. Explicitly call out anything that cannot be determined from the repository.
12. At the end, provide a concise **Implementation Summary** and wait for approval before making any code changes.