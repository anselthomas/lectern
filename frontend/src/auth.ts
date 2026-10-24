import {
  AuthenticationDetails, CognitoUser, CognitoUserAttribute, CognitoUserPool, CognitoUserSession,
} from "amazon-cognito-identity-js";

// Public identifiers (not secrets) of the user pool and its web client, supplied at build time:
// deploy/deploy-web.sh reads them from the CloudFormation stack (see frontend/.env.example for local builds).
function env(name: "VITE_USER_POOL_ID" | "VITE_CLIENT_ID"): string {
  const value = import.meta.env[name];
  if (!value) throw new Error(`${name} is not set; build with deploy/deploy-web.sh or a .env.local file`);
  return value;
}
const pool = new CognitoUserPool({ UserPoolId: env("VITE_USER_POOL_ID"), ClientId: env("VITE_CLIENT_ID") });

function user(email: string) {
  return new CognitoUser({ Username: email.trim().toLowerCase(), Pool: pool });
}

export function friendlyError(e: any): string {
  const code = e?.code || e?.name;
  switch (code) {
    case "NotAuthorizedException": return "That email and password don't match.";
    case "UserNotFoundException": return "That email and password don't match.";
    case "UsernameExistsException": return "An account with this email already exists. Sign in instead.";
    case "InvalidPasswordException": return "Use at least 8 characters, including a number and a lowercase letter.";
    case "CodeMismatchException": return "That code isn't right. Check the email and try again.";
    case "ExpiredCodeException": return "That code has expired. Send a new one.";
    case "LimitExceededException":
    case "TooManyRequestsException": return "Too many attempts. Wait a minute and try again.";
    case "UserNotConfirmedException": return "Verify your email first.";
    case "InvalidParameterException": return e?.message?.includes("email") ? "Enter a valid email address." : (e?.message ?? "Check the form and try again.");
    default: return e?.message ?? "Something went wrong. Try again.";
  }
}

export function signUp(name: string, email: string, password: string): Promise<void> {
  return new Promise((resolve, reject) => {
    pool.signUp(email.trim().toLowerCase(), password,
      [new CognitoUserAttribute({ Name: "email", Value: email.trim().toLowerCase() }),
       new CognitoUserAttribute({ Name: "name", Value: name.trim() })],
      [], (err) => (err ? reject(err) : resolve()));
  });
}

export function confirmSignUp(email: string, code: string): Promise<void> {
  return new Promise((resolve, reject) =>
    user(email).confirmRegistration(code.trim(), true, (err) => (err ? reject(err) : resolve())));
}

export function resendCode(email: string): Promise<void> {
  return new Promise((resolve, reject) =>
    user(email).resendConfirmationCode((err) => (err ? reject(err) : resolve())));
}

/** Passwords pasted from a chat app often bring a space along; if the exact text fails, try it trimmed once. */
export async function signIn(email: string, password: string): Promise<CognitoUserSession> {
  try {
    return await signInExact(email, password);
  } catch (e: any) {
    if (e?.code === "NotAuthorizedException" && password.trim() && password.trim() !== password) return signInExact(email, password.trim());
    throw e;
  }
}

function signInExact(email: string, password: string): Promise<CognitoUserSession> {
  return new Promise((resolve, reject) => {
    user(email).authenticateUser(new AuthenticationDetails({ Username: email.trim().toLowerCase(), Password: password }), {
      onSuccess: resolve,
      onFailure: reject,
      newPasswordRequired: () => reject({ code: "NewPasswordRequired", message: "Choose a new password using “Forgot password”." }),
    });
  });
}

export function forgotPassword(email: string): Promise<void> {
  return new Promise((resolve, reject) =>
    user(email).forgotPassword({ onSuccess: () => resolve(), onFailure: reject, inputVerificationCode: () => resolve() }));
}

export function confirmPassword(email: string, code: string, password: string): Promise<void> {
  return new Promise((resolve, reject) =>
    user(email).confirmPassword(code.trim(), password, { onSuccess: () => resolve(), onFailure: reject }));
}

export function signOut() {
  pool.getCurrentUser()?.signOut();
}

/** Current ID token, refreshed by the SDK when needed. Null when signed out. */
export function idToken(): Promise<string | null> {
  const u = pool.getCurrentUser();
  if (!u) return Promise.resolve(null);
  return new Promise((resolve) => {
    u.getSession((err: any, session: CognitoUserSession | null) => {
      if (err || !session?.isValid()) return resolve(null);
      resolve(session.getIdToken().getJwtToken());
    });
  });
}

export function hasSession(): boolean {
  return !!pool.getCurrentUser();
}
