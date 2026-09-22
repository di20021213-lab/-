package ru.kolhoz.dyshlo;

import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebSettings;
import android.webkit.WebView;

/** Обёртка вокруг офлайновой сборки игры.

    Внутри лежит тот же файл, что открывается в браузере, — вся игра и вся
    графика одной страницей. Сервер не нужен: счёт, время созревания и
    прогресс считает сама страница, сохраняя их в хранилище телефона. */
public class MainActivity extends Activity {
  private WebView web;

  @Override protected void onCreate(Bundle state) {
    super.onCreate(state);
    web = new WebView(this);
    WebSettings s = web.getSettings();
    s.setJavaScriptEnabled(true);
    s.setDomStorageEnabled(true);          // без него прогресс не сохранится
    s.setAllowFileAccess(true);
    s.setDatabaseEnabled(true);
    s.setLoadWithOverviewMode(true);
    s.setUseWideViewPort(true);
    s.setTextZoom(100);                    // системный «крупный шрифт» ломает вёрстку
    web.setOverScrollMode(View.OVER_SCROLL_NEVER);
    setContentView(web);
    if(state != null) web.restoreState(state);
    else web.loadUrl("file:///android_asset/index.html");
  }

  /** Кнопка «назад» закрывает окно в игре, а не приложение. */
  @Override public void onBackPressed() {
    if(web.canGoBack()) web.goBack();
    else super.onBackPressed();
  }

  @Override protected void onSaveInstanceState(Bundle out) {
    super.onSaveInstanceState(out);
    web.saveState(out);
  }
}
