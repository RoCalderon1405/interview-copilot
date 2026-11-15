# Example interview questions

Q: What is authentication?
A: Authentication verifies who a user is. For example, a REST API can verify a signed access token to identify the current user.

Q: What is authorization?
A: Authorization determines what an authenticated user is allowed to access. For example, role-based access control limits access to protected API endpoints.

Q: What is refresh token rotation?
A: Refresh token rotation issues a new refresh token each time the current one is used and invalidates the old one. Reuse detection can help identify a stolen token.

Q: Why use dependency injection?
A: Dependency injection supplies a component's dependencies from outside. It makes code easier to test and reduces coupling between classes.
