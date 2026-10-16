#!/usr/bin/env python3
"""pomnote の Android アプリ（APK）のプロジェクト一式を、この1ファイルから書き出す。
GitHub Actions が実行して APK を作る。

中身は「https://aji-daze.github.io/pomnote/ を開くだけの、枠のないブラウザ（WebView）」。
アプリ本体（書く画面・辞書・同期など）は Web 側にあり、Web 側を更新すれば APK も新しくなる。

セキュリティの方針
- 開くのは pomnote のページだけ。ほかのリンクは外のブラウザに渡す（intent: など危ない形式は開かない）
- ページからアプリの内部（Java）を呼べる口（JavaScript インターフェース）は作らない
- 端末のファイルを WebView から直接読ませない（ファイルは「ファイルを選ぶ」画面で選んだものだけ）
- 暗号化されていない通信（http）は使わない。デバッグ接続は切る。自動バックアップは使わない
- 求める権限はインターネットだけ
"""
import os
import urllib.request

ROOT = os.getcwd()
PKG = "app.pomnote"
PKG_DIR = "app/src/main/java/app/pomnote"
RES = "app/src/main/res"
SITE = "https://aji-daze.github.io/pomnote/"


def w(path, content):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


# ---------------------------------------------------------------- gradle
w("settings.gradle", r"""pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "pomnote"
include ':app'
""")

w("build.gradle", r"""plugins {
    id 'com.android.application' version '8.7.3' apply false
}
""")

w("gradle.properties", r"""org.gradle.jvmargs=-Xmx3g -Dfile.encoding=UTF-8
""")

w("app/build.gradle", r"""plugins {
    id 'com.android.application'
}

android {
    namespace 'app.pomnote'
    compileSdk 35

    defaultConfig {
        applicationId 'app.pomnote'
        minSdk 24
        // 35 にすると Android 15 で画面の端まで描く表示が強制され、上部がカメラの穴に重なるので 34 にしておく
        targetSdk 34
        versionCode Integer.parseInt(System.getenv('VERSION_CODE') ?: '1')
        versionName '1.0.' + (System.getenv('VERSION_CODE') ?: '1')
    }

    // 署名鍵とパスワードは GitHub Secrets から渡す（リポジトリには置かない）
    signingConfigs {
        release {
            storeFile file('../signing.p12')
            storeType 'pkcs12'
            storePassword System.getenv('SIGNING_PASSWORD')
            keyAlias 'pomnote'
            keyPassword System.getenv('SIGNING_PASSWORD')
        }
    }

    buildTypes {
        release {
            signingConfig signingConfigs.release
            minifyEnabled false
        }
    }

    compileOptions {
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }

    lint {
        abortOnError false
        checkReleaseBuilds false
    }
}

tasks.withType(JavaCompile) {
    options.encoding = 'UTF-8'
}
""")

# ---------------------------------------------------------------- manifest
w("app/src/main/AndroidManifest.xml", r"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.INTERNET" />

    <application
        android:label="pomnote"
        android:icon="@mipmap/ic_launcher"
        android:roundIcon="@mipmap/ic_launcher"
        android:theme="@style/AppTheme"
        android:allowBackup="false"
        android:fullBackupContent="false"
        android:dataExtractionRules="@xml/no_backup"
        android:usesCleartextTraffic="false">

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:launchMode="singleTask"
            android:windowSoftInputMode="adjustResize"
            android:configChanges="orientation|screenSize|smallestScreenSize|screenLayout|keyboard|keyboardHidden|navigation|uiMode">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
""")

# Android 12 以降の自動バックアップ・機種変更時の引き継ぎから、アプリの中身を外す（原稿は同期で引き継ぐ）
w(f"{RES}/xml/no_backup.xml", r"""<?xml version="1.0" encoding="utf-8"?>
<data-extraction-rules>
    <cloud-backup>
        <exclude domain="root" />
        <exclude domain="file" />
        <exclude domain="database" />
        <exclude domain="sharedpref" />
        <exclude domain="external" />
    </cloud-backup>
    <device-transfer>
        <exclude domain="root" />
        <exclude domain="file" />
        <exclude domain="database" />
        <exclude domain="sharedpref" />
        <exclude domain="external" />
    </device-transfer>
</data-extraction-rules>
""")

# ---------------------------------------------------------------- java
w(f"{PKG_DIR}/MainActivity.java", r"""package app.pomnote;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    static final String HOST = "aji-daze.github.io";
    static final String PATH = "/pomnote/";
    static final String BASE = "https://" + HOST + PATH;
    static final int PICK_FILE = 1;

    // 戻るボタン: パネル・辞書・読書・ダイアログが開いていれば閉じる。何も開いていなければ true 以外を返す
    static final String BACK_JS = "(function(){"
        + "var d=document.querySelector('dialog[open]');"
        + "if(d){var b=[].slice.call(d.querySelectorAll('button')).filter(function(x){return /閉じる|キャンセル/.test(x.textContent);})[0];"
        + "if(b){b.click();}else{d.close();}return true;}"
        + "if(document.querySelector('#panel:not([hidden]),#bookView:not([hidden]),#dictView:not([hidden]),#readBar:not([hidden])')){"
        + "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;}"
        + "return false;})()";

    static final String OFFLINE_HTML = "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
        + "<body style='margin:0;padding:48px 24px;background:#fbf9f3;color:#23211c;font-family:serif;line-height:1.8'>"
        + "<h2 style='font-weight:600'>pomnote を開けませんでした</h2>"
        + "<p>初めて開くときだけ、インターネットへの接続が必要です。Wi-Fi などにつないでから、もう一度読み込んでください。<br>"
        + "一度開けば、次からはネットがなくても使えます。</p>"
        + "<p><a href='" + BASE + "' style='display:inline-block;padding:12px 20px;border-radius:8px;background:#b5452b;color:#fff;text-decoration:none'>もう一度読み込む</a></p>";

    private WebView web;
    private ValueCallback<Uri[]> fileCallback;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Window win = getWindow();
        win.setStatusBarColor(Color.parseColor("#FBF9F3"));
        if (Build.VERSION.SDK_INT >= 23) {
            win.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }

        WebView.setWebContentsDebuggingEnabled(false);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);   // 原稿は IndexedDB に保存される
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setSupportMultipleWindows(false);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setTextZoom(100);
        if (Build.VERSION.SDK_INT >= 26) s.setSafeBrowsingEnabled(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if (isOwn(u)) return false;
                openOutside(u);
                return true;
            }

            // 初めて開くときにネットがないと、ページを保存できていないので開けない。案内を出す
            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) v.loadDataWithBaseURL(null, OFFLINE_HTML, "text/html", "utf-8", null);
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            // 読書の「ファイルを開く」など。選んだファイルだけをページに渡す
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = cb;
                try {
                    startActivityForResult(params.createIntent(), PICK_FILE);
                } catch (ActivityNotFoundException e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });

        setContentView(web);
        if (state != null) web.restoreState(state);
        else web.loadUrl(BASE);
    }

    static boolean isOwn(Uri u) {
        return u != null && "https".equals(u.getScheme()) && HOST.equals(u.getHost())
            && u.getPath() != null && u.getPath().startsWith(PATH);
    }

    // ほかのサイトは外のブラウザで開く。http(s)・メール以外の形式（intent: など）は開かない
    void openOutside(Uri u) {
        String scheme = u.getScheme() == null ? "" : u.getScheme();
        if (!scheme.equals("https") && !scheme.equals("http") && !scheme.equals("mailto")) return;
        try {
            Intent i = new Intent(Intent.ACTION_VIEW, u);
            i.addCategory(Intent.CATEGORY_BROWSABLE);
            startActivity(i);
        } catch (ActivityNotFoundException ignored) {
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        if (request == PICK_FILE && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(request, result, data);
    }

    @Override
    public void onBackPressed() {
        web.evaluateJavascript(BACK_JS, value -> {
            if ("true".equals(value)) return;
            if (web.canGoBack()) web.goBack();
            else finish();
        });
    }

    @Override
    protected void onPause() {
        super.onPause();
        web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
""")

# ---------------------------------------------------------------- res
w(f"{RES}/values/styles.xml", r"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="@android:style/Theme.Material.Light.NoActionBar">
        <item name="android:windowBackground">@color/paper</item>
        <item name="android:statusBarColor">@color/paper</item>
        <item name="android:navigationBarColor">@color/paper</item>
    </style>
</resources>
""")
w(f"{RES}/values/colors.xml", r"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="paper">#FBF9F3</color>
</resources>
""")

# ランチャーアイコンは、公開中のアプリのアイコンをそのまま使う
icon_path = os.path.join(ROOT, RES, "mipmap-xxxhdpi", "ic_launcher.png")
os.makedirs(os.path.dirname(icon_path), exist_ok=True)
urllib.request.urlretrieve(SITE + "icons/icon-192.png", icon_path)

# ---------------------------------------------------------------- emulator test
# エミュレータ上で、インストール → 起動 → 画面撮影 までを試す（CI 用）
w("emu.sh", r"""#!/bin/bash
set -x
APK=app/build/outputs/apk/release/app-release.apk
{
  adb install -r "$APK"
  adb shell dumpsys package app.pomnote | grep -E "versionName|versionCode|targetSdk|minSdk|requested permissions|android.permission" | head -12
  # エミュレータのネットがつながるまで待つ（最大2分）
  for i in $(seq 1 24); do
    adb shell ping -c 1 -W 3 aji-daze.github.io > /dev/null 2>&1 && { echo "network ready after $i tries"; break; }
    sleep 5
  done
  adb logcat -c
  adb shell am start -W -n app.pomnote/.MainActivity
  sleep 30
  echo "pid: $(adb shell pidof app.pomnote)"
} > emu.log 2>&1
adb exec-out screencap -p > shot-app.png || true
adb logcat -d -b crash > crash.log 2>&1 || true
adb logcat -d | grep -iE "chromium|pomnote|AndroidRuntime" | tail -80 >> emu.log || true
""")

print("generated", PKG)
