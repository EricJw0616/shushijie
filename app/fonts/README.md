# 随应用提供的 PDF 中文字体

PDF 使用本目录中的 TrueType 字体，并把实际使用的字形嵌入文件。Windows、Linux、macOS 使用同一份字体文件，不读取开发者个人字体目录，也不需要浏览器或系统打印组件。

- `NotoSansSC-Regular.ttf`：正文，字重 400。
- `NotoSansSC-Bold.ttf`：标题与强调，字重 700。
- `OFL-NotoSansSC.txt`：上游版权声明及完整 SIL Open Font License 1.1，分发时必须一同保留。
- `manifest.json`：固定的上游提交、下载地址及输入、输出 SHA-256。

来源：[Google Fonts / Noto Sans SC](https://github.com/google/fonts/tree/2894aab31764f10f29c421bdfd2340d3b382d384/ofl/notosanssc)。这两个文件由上游可变 TrueType 字体通过 FontTools 的 `instantiateVariableFont` 生成静态字重；保留全部字形，内部字体族重命名为 `BookWorld Sans SC`。它们继续采用上游 OFL 1.1 许可。

应用运行时不需要 FontTools，也不下载字体。部署时复制整个 `app/fonts` 目录即可；不要复制其他电脑的 `.venv`，应在目标操作系统重新建立 Python 环境。

如需要替换字体，可以把 `BOOKDISTILL_PDF_FONT` 设置为可嵌入的 TrueType 字体文件路径。导出前会检查文字是否有对应字形；缺字时明确提示，不会生成静默缺字的交付稿。
