// ビルド時に埋め込まれる公開設定値(NEXT_PUBLIC_*)の必須チェック。
//
// NEXT_PUBLIC_*はnext buildのときにJSへ値が埋め込まれる。埋め込まれるのはソースに
// `process.env.NEXT_PUBLIC_X`と直接書いた箇所だけなので、この関数はprocess.envを
// 自分で読まず、呼び出し側で読んだ値を受け取る。
//
// 未設定ならモジュール読み込み時に例外を投げる。静的エクスポートのビルドはページを
// 事前描画する際にこのモジュールを読み込むため、設定漏れは「ビルド失敗」として表に出る
// (dev環境の値に黙ってつながる事故を防ぐ)。
export function requirePublicEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `${name} が設定されていません。ローカルでは web/.env.example を参考に web/.env.local を作成してください。`,
    );
  }
  return value;
}
