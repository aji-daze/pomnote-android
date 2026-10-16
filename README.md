# pomnote-android

[pomnote](https://aji-daze.github.io/pomnote/)（オフラインで使える執筆アプリ）を、Android アプリとして開くための APK を作ります。

- APK は [Releases](https://github.com/aji-daze/pomnote-android/releases/latest) の `pomnote.apk`。リリースの説明に APK と署名証明書の SHA-256 を載せています。
- `generate.py` が Android プロジェクトを書き出し、GitHub Actions がビルド・署名・エミュレータでの起動確認を行います。
- 署名鍵はリポジトリに置かず、GitHub Secrets（`SIGNING_KEYSTORE_B64` / `SIGNING_PASSWORD`）から渡します。
- アプリは pomnote のページだけを開く WebView です。ほかのリンクは外のブラウザで開き、ページからアプリの内部を呼ぶ口は作っていません。権限はインターネットのみです。
