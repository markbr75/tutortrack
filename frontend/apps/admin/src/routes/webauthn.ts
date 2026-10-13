/* WebAuthn browser helpers (E03-T08): the API sends and expects JSON with base64url
 * binary fields (py_webauthn's `options_to_json` / `parse_*_credential_json` shapes). */

type Json = Record<string, unknown>;

export function passkeysSupported(): boolean {
  return (
    typeof window !== "undefined" && "PublicKeyCredential" in window && !!navigator.credentials
  );
}

function toBuffer(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function toBase64url(value: ArrayBuffer | null): string | null {
  if (!value) return null;
  let binary = "";
  for (const byte of new Uint8Array(value)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(list)) return undefined;
  return list.map((d: Json) => ({
    ...(d as object),
    type: "public-key" as const,
    id: toBuffer(String(d.id)),
  }));
}

/** Register a passkey: `options` from `POST /me/passkeys/options`. */
export async function createPasskey(options: Json): Promise<Json> {
  const user = options.user as Json;
  const credential = (await navigator.credentials.create({
    publicKey: {
      ...(options as object),
      challenge: toBuffer(String(options.challenge)),
      user: { ...(user as object), id: toBuffer(String(user.id)) },
      excludeCredentials: descriptors(options.excludeCredentials),
    } as PublicKeyCredentialCreationOptions,
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("cancelled");
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      attestationObject: toBase64url(response.attestationObject),
      transports: response.getTransports ? response.getTransports() : [],
    },
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

/** Sign in with a passkey: `options` from `POST /auth/passkey/options`. */
export async function getPasskey(options: Json): Promise<Json> {
  const credential = (await navigator.credentials.get({
    publicKey: {
      ...(options as object),
      challenge: toBuffer(String(options.challenge)),
      allowCredentials: descriptors(options.allowCredentials),
    } as PublicKeyCredentialRequestOptions,
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("cancelled");
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      authenticatorData: toBase64url(response.authenticatorData),
      signature: toBase64url(response.signature),
      userHandle: toBase64url(response.userHandle),
    },
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}
