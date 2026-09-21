# ハーネスエンジニアリングの導入テンプレート

要件・設計・実装・テストの対応を管理し、変更後に確認が必要な文書を検出します。テストの失敗から成功までの記録と、実行を許可するコマンドの設定も扱います。

[英語版](README.en.md) · [操作手順](docs/USAGE.md) · [設計と制約](docs/ARCHITECTURE.md)

## クローン後に試す

必要なものはGitと **Python 3.10以上** です。Pythonはこのツールを動かすために使い、対象アプリの開発言語は限定していません。付属の利用例には、追加パッケージやAPIキーは不要です。

クローンしたディレクトリで実行してください。

```sh
# 実行環境と付属の利用例を確認します
python3 kit.py doctor
python3 kit.py demo
```

Windowsでは `python3` を `py -3` へ置き換えてください。`dev.cmd` やPowerShellの `./dev.ps1` も使えます。macOS・Linuxでは `./dev` が短い呼び出し方です。

`demo` は一時的な作業場所で動きます。クローンしたテンプレートの設定や成果物を、確認済みの状態へ変更しません。

## 仕様と検証を管理する

Markdownの冒頭に文書ID、上位の要件・設計、対応する実装・テストのパスを記載します。`.agentkit/harness.json` で対象範囲と検証コマンドを指定します。

```sh
# 変更箇所と、確認が必要な文書を確認します
python3 kit.py impact
python3 kit.py inspect
```

初期状態には確認済みの記録がないため、`inspect` は未確認として扱います。付属例の流れは `demo`、実際の変更手順は [操作手順](docs/USAGE.md) を参照してください。

TDDの記録にはJUnit形式の出力を使います。起動エラーや未実行のテストを失敗の証拠にせず、同じテストが失敗してから成功したことを確認します。設計の内容やテストの十分さは、人が判断する必要があります。

GitフックとCodex・Claude Codeのフックは任意で導入します。生成した設定だけでは有効にならず、既存設定との調整やツール側の信頼設定が必要です。ローカルフックは利用者が回避できるため、サーバー側の権限管理を代替しません。

## 自分のプロジェクトへ導入する

新しく始める場合は、空の作業場所を作成できます。

```sh
# テンプレートと実行ツールを新しい作業場所へコピーします
python3 kit.py new ../my-project
```

既存のプロジェクトへ追加する場合は、追加予定のファイルを確認してから適用します。

```sh
# 追加内容を確認してから適用します
python3 kit.py install --target ../existing-project
python3 kit.py install --target ../existing-project --apply
```

既存のAGENTS.md、CLAUDE.md、設定、フックは上書きしません。`.agentkit/harness.example.json` のパスやコマンドを実際のプロジェクトへ合わせ、`.agentkit/harness.json` として保存してください。導入先のディレクトリでは `python3 .agentkit/tools/harness/kit.py --root . inspect` で設定を確認できます。

## 設計上の範囲

このテンプレートは手元で使う開発用ツールです。ローカルの設定や記録は、利用者自身が変更できます。実行権限を制限する場合は、認証情報や実行環境側でも制御してください。詳しい対応範囲は [設計と制約](docs/ARCHITECTURE.md) に記載しています。

ツール自体を変更したときの検査は `python3 kit.py check` で実行できます。ライセンスは [MIT](LICENSE) です。第三者のコードの出典は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
