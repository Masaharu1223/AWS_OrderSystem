// Cognito User Pools API(cognito-idp)への直接fetch。api.tsのAPI Gatewayとは別オリジン・
// 別プロトコル(AWS JSON-1.1)のため、認証をapi.tsのapiFetchには混ぜず、ここに分離する。
// USER_PASSWORD_AUTH/REFRESH_TOKEN_AUTHはUserPoolClient(シークレット無しのpublicクライアント)に
// 対して未署名で呼べるため、IAM認証情報やSRPライブラリは不要(tasks/todo.md §31)。
const STAFF_CLIENT_ID = process.env.NEXT_PUBLIC_STAFF_CLIENT_ID ?? "71i90t8sqoamtmnp8qp3r58ura";
const COGNITO_IDP_URL = "https://cognito-idp.ap-northeast-1.amazonaws.com/";

const STORAGE_KEY = "mobileOrder.staffAuth";

export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}

export interface AuthTokens {
  idToken: string;
  accessToken: string;
  refreshToken: string;
  // IdTokenのexpクレーム(UNIX秒)。サイレントリフレッシュのタイミング判定に使う。
  expiresAt: number;
}

interface CognitoAuthenticationResult {
  IdToken: string;
  AccessToken: string;
  // REFRESH_TOKEN_AUTHの応答には含まれない(ローテーション未設定のため再利用される)。
  RefreshToken?: string;
}

async function callCognito(
  target: "InitiateAuth",
  body: Record<string, unknown>,
): Promise<{ AuthenticationResult: CognitoAuthenticationResult }> {
  const res = await fetch(COGNITO_IDP_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    // Cognitoのエラー応答は{__type, message}形式。詳細をUIにそのまま出すと情報を与えすぎるため、
    // 呼び出し側(StaffLoginForm)で「ユーザー名またはパスワードが違います」等に丸めて表示する。
    throw new AuthError(typeof data?.message === "string" ? data.message : `auth failed: ${res.status}`);
  }
  return data;
}

function decodeExp(idToken: string): number {
  const payload = idToken.split(".")[1];
  const json = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))) as { exp: number };
  return json.exp;
}

function toTokens(result: CognitoAuthenticationResult, previousRefreshToken?: string): AuthTokens {
  const refreshToken = result.RefreshToken ?? previousRefreshToken;
  if (!refreshToken) {
    throw new AuthError("refresh token missing from Cognito response");
  }
  return {
    idToken: result.IdToken,
    accessToken: result.AccessToken,
    refreshToken,
    expiresAt: decodeExp(result.IdToken),
  };
}

export async function signIn(username: string, password: string): Promise<AuthTokens> {
  const { AuthenticationResult } = await callCognito("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: STAFF_CLIENT_ID,
    AuthParameters: { USERNAME: username, PASSWORD: password },
  });
  return toTokens(AuthenticationResult);
}

export async function refreshTokens(refreshToken: string): Promise<AuthTokens> {
  const { AuthenticationResult } = await callCognito("InitiateAuth", {
    AuthFlow: "REFRESH_TOKEN_AUTH",
    ClientId: STAFF_CLIENT_ID,
    AuthParameters: { REFRESH_TOKEN: refreshToken },
  });
  return toTokens(AuthenticationResult, refreshToken);
}

// sessionStorageアクセスはブラウザ実行時限定(useEffect/イベントハンドラ内)に呼ぶこと。
// web/src/lib/session.tsと同じ規約(レンダー中に呼ぶと静的エクスポートのハイドレーション不整合を招く)。
export function getStoredTokens(): AuthTokens | null {
  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthTokens;
  } catch {
    return null;
  }
}

export function setStoredTokens(tokens: AuthTokens): void {
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
}

export function clearStoredTokens(): void {
  window.sessionStorage.removeItem(STORAGE_KEY);
}
