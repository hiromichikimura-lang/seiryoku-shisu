
# 政党インパクト指数

政党のインパクトを、国会・都道府県議会・市区町村議会の議席占有率と、知事・市区町村長のポスト占有率から算出する非公式の定点観測プロジェクトです。選挙ドットコムベースの議席台帳のカバレッジが97%前後に達したことで、月1回を目安とするnote記事のスケジュールを目指しています。算出式・データソースの詳細は [`design_document.tex`](design_document.tex) / [`design_document.pdf`](design_document.pdf) を参照してください。

## セットアップ

```bash
pip install -r requirements.txt
```

## 実行

```bash
PYTHONPATH=src python3 -m seiryoku.cli
```

初回実行時は市区町村決算カード(47都道府県ぶん、数十ファイル)をダウンロードするため数分かかります。ダウンロードした生データは `cache/` に、算出結果は `output/YYYY-MM-DD.json` に保存されます。

## 定期リフレッシュ(任意)

義務ではありませんが、`systemd/` 以下のunitファイルを使うと、データを定期的に新鮮に保てます。PCが常時起動していなくても、次回起動時に前回分を追いつき実行できます(`Persistent=true`)。

```bash
mkdir -p ~/.config/systemd/user
cp systemd/*.service systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now seiryoku-shisu.timer
```

## 構成

```
src/seiryoku/
  fetch/
    diet.py           # 衆議院・参議院の会派別議席数
    local_parties.py  # 総務省: 地方議会・首長の党派別人員調
    budgets.py         # 財務省の国家予算、総務省の都道府県・市区町村決算カード
    codes.py           # 市区町村コード改正履歴(合併の追跡)
  lineage.py            # 政党名の名寄せ(改称・表記ゆれの吸収)
  index.py              # 議会指数 I_p・首長指数 E_p の算出
  cli.py                 # 月次実行のエントリポイント
```

## 現時点での既知の制約

- 首長の推薦・支持政党による無所属の仕分けは実装済みです。公開されている年版(2018〜2025年の8年ぶん)を遡って合算し、知事47/47・市区町村長1718自治体ぶんを確認済みです。政党の合流・分裂時の実測配分は未実装です(`design_document.tex`の「今後の課題」を参照)。
- 党派転換で重み付けた注目度指数の変種$W_p^{\text{turnover}}(T)$・その補集指標$L_p^{\text{turnover}}(T)$は首長(知事・市区町村長)ぶんを実装済みです。議会(都道府県議会・市区町村議会)ぶんは未実装です。
- 財務省の予算シート名(`MOF_LATEST_SHEET`)は元号が変わるたびに手動更新が必要です。

## AIの活用について

本プロジェクトの指数設計・データソース調査・実装にはAI(Claude)を活用しています。

## ライセンス

コード(`src/` 以下)は [MIT License](LICENSE) です。`design_document.tex`・本READMEの説明文・noteの記事等の文章については著作権を放棄していません。
