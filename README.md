# 宍粟市一宮町 暑さ指数(WBGT) 自動更新ページ

環境省「熱中症予防情報サイト」のオープンデータから、宍粟市一宮町（地点番号 **63251**）の
暑さ指数(WBGT)を取得し、以下を表示する静的ページを自動生成します。

- 最新の速報値（現在のWBGTと警戒レベル）
- 今シーズン（5〜9月）で **WBGT 28以上**・**31以上**だった日数と該当日
- 直近7日間の推移と予測の時系列グラフ

GitHub Actions が定期実行してビルドし、GitHub Pages に公開します。
WordPress 記事へは公開URLを iframe で埋め込むだけです。

## 更新頻度

- **5〜9月**：1時間ごと（自動）
- **オフシーズン**：週1回（毎週月曜・自動）

## セットアップ

VSCode のターミナルで実施できます。

```bash
# このフォルダで実行（gh CLI がログイン済みの場合）
gh repo create wbgt-shiso-ichinomiya --public --source=. --push
```

`gh` を使わない場合は GitHub 上で空リポジトリを作成し、次のように push します。

```bash
git init
git add .
git commit -m "初期構築：WBGT自動更新ページ"
git branch -M main
git remote add origin https://github.com/<ユーザー名>/wbgt-shiso-ichinomiya.git
git push -u origin main
```

push 後：

1. リポジトリの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にする。
2. **Actions** タブ → `update` ワークフロー → **Run workflow**（手動実行）で初回公開。
3. 公開URL `https://<ユーザー名>.github.io/wbgt-shiso-ichinomiya/` を確認。

## WordPress への埋め込み

投稿編集で「カスタムHTML」ブロックを追加し、次を貼り付け（URLは自分のものに置換）。

```html
<iframe src="https://<ユーザー名>.github.io/wbgt-shiso-ichinomiya/"
        style="width:100%;border:0;height:1000px" loading="lazy"
        title="宍粟市一宮町 暑さ指数(WBGT)"></iframe>
```

高さ（`height`）は実際の表示に合わせて調整してください。

## ローカルでの確認

```bash
python3 build.py
# public/index.html が生成されるのでブラウザで開く
open public/index.html   # macOS
```

## 注意・制約

- GitHub Actions の cron は厳密な毎時ではありません（混雑時に数分〜十数分の遅延・まれにスキップ）。
- **リポジトリが60日間無操作だと schedule が自動停止**します。年1回程度、手動実行かコミットで再有効化してください。
- 環境省データは更新に時間差があり、最新時刻が空のことがあります（最後の非空値を速報として表示）。
- 本ページは **参考情報**です。出典（環境省 熱中症予防情報サイト）を必ず明記しています。

## ファイル構成

```
.
├─ .github/workflows/update.yml  # 定期実行 → ビルド → Pagesデプロイ
├─ build.py                      # データ取得・集計・HTML生成（標準ライブラリのみ）
├─ public/index.html            # 生成物（Actionが毎回生成。コミット不要）
└─ README.md
```

出典：[環境省 熱中症予防情報サイト](https://www.wbgt.env.go.jp/)
