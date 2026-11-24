# OCR 子系统（生产可部署）

> 目标：把「图片里的文字」识别出来，作为原生文字层的补洞；不重写全书，不替换已有干净文本。
>
> 引擎：**RapidOCR（PP-OCR 模型 + ONNX Runtime）**，Apache-2.0，Linux/Windows/macOS 都能跑，CPU 可部署，换 `onnxruntime-gpu` 可上 GPU。
>
> 明确不用 macOS Vision 做生产：它只是开发机验证，部署到 Linux 服务器/客户现场带不过去。

## 1. 为什么选 RapidOCR

| 选项 | 结论 |
|---|---|
| macOS Vision | 只能开发机用，不能交付；不进入生产 |
| PaddleOCR 原生 | 精度好，但 PaddlePaddle 依赖重、部署环境挑；可作为后续高精度适配器 |
| **RapidOCR（PP-OCR ONNX）** | **默认生产**：模型随包、Linux/CPU 可跑、Docker 小、Apache-2.0、中文/竖排/艺术字可用 |
| 云 OCR | 可选增强；数据出境/按页计费/供应商锁定，私有化客户通常不接受 |

模型是 PP-OCRv4 检测 + 方向分类 + 识别，已随 `rapidocr-onnxruntime` 包分发（约 16MB），不依赖运行时外网。

## 2. 目录

```
platform/engine/ocr/
  types.py          OCRLine / OCRPage
  provider.py       OCRProvider 接口
  rapid_provider.py RapidOCR 适配器
  render.py         pypdfium2 渲染 + 原生文字层读取
  router.py         页面级路由：native / ocr
  fields.py         封面/书名页字段抽取 + A/B/C 验收
  pipeline.py       路由→渲染→识别→字段→落盘
  cli.py            命令行
  tests/            不加载模型的单元测试
```

PDF 渲染用 **pypdfium2**（PDFium，Apache-2.0/BSD 系），不用 PyMuPDF（AGPL-3.0，商用要另买许可）。

## 3. 产物

```
platform/out/<code>/ocr/
  plan.json       每页动作 + 原因
  pages.jsonl     每页文本、行、bbox、置信度、引擎/版本
  fields.json     书名/出版社/作者 + A/B/C + 证据
  manifest.json   引擎、版本、DPI、页范围
  images/         页面图（可配置不落盘）
```

`fields.json` 里书名的证据形状：

```json
{
  "page": 5,
  "quote": "国之脊梁——中国院士的科学人生百年",
  "parts": ["国之脊梁", "中国院士的科学人生百年"],
  "source": "ocr",
  "engine": "rapidocr",
  "engine_version": "1.4.4",
  "confidence": 0.9632,
  "bbox": [1492, 195, 1881, 2084],
  "cross_check": "library",
  "accept": "A"
}
```

`quote` 是两块竖排的拼接值，`parts` 保留每块，校验时逐块对 OCR 页文本；不把拼接串当“连续原文”。

## 4. A/B/C 验收

| 级别 | 条件 | 处理 |
|---|---|---|
| A | OCR 置信度 ≥ 0.5 且与书目库/CIP 书名一致 | 自动采用，进交付 |
| B | OCR 置信度 ≥ 0.85，无独立源 | 采用，标 `source=ocr`，抽样复核 |
| C | 低置信/冲突/选不出 | 人工 |

注意：置信度不是校准过的准确率；A 类靠的是**独立源交叉校验**，不是“模型很自信”。

## 5. 页面路由

`router.plan()` 只对以下页 OCR：

- 原生文字层为空；
- 原生文字层乱码/异常字符；
- 指定页强制 OCR（封面、书名页、难页）；
- 原生文字过短。

其余页保持原生文字。整本无脑 OCR 又贵又容易把干净文本弄脏。

## 6. 运行

本地（开发机，仅验证）：

```bash
cd platform/engine
python -m ocr.cli --code B59 \
  --pdf ../../app/data/uploads/20261111-124312-b7614a/original.pdf \
  --pages 5 --force \
  --library ../../app/data/library.json
```

Docker（生产，Linux）：

```bash
docker build -f platform/engine/Dockerfile.ocr -t bookdistill-ocr .
docker run --rm \
  -v "$PWD/platform/out:/out" \
  -v "$PWD/app/data:/data" \
  bookdistill-ocr --code B59 \
  --pdf /data/uploads/20261111-124312-b7614a/original.pdf \
  --pages 5 --force \
  --library /data/library.json \
  --outdir /out/B59/ocr
```

GPU：把 `requirements-ocr.txt` 里的 `onnxruntime` 换成 `onnxruntime-gpu`，基础镜像换 CUDA runtime，并给容器 `--gpus all`。

## 7. 和 47 项交付的衔接

复跑顺序（先 OCR，再出版信息，再交付）：

```bash
cd platform/engine
python -m ocr.cli --code B59 --pdf ../../app/data/uploads/20261111-124312-b7614a/original.pdf \
  --pages 5 --force --library ../../app/data/library.json
python3 publication.py --all --library ../../app/data/library.json
python3 delivery.py --all
cd ../.. && python3 标签体系/check_location.py
```

Web/API 进程不需要安装 OCR 依赖；OCR 是独立 worker。

上传钩子（可选）：`app/runner.py` 在 `BOOKDISTILL_OCR=1` 时会对 PDF 前 10 页跑 OCR，再进 publication。
- 私有化单镜像：在 app 镜像里也装 `requirements-ocr.txt` 即可；
- SaaS：建议把这一步改成调用独立 OCR worker（队列），不要给 Web 进程装 GPU/模型。

- `publication.py` 读 `out/<code>/ocr/fields.json`：原生/导入书名没有证据时，用 OCR 书名（`method=ocr`）。
- `delivery.py` 原样把 OCR 证据带进长表。
- `check_location.py` 校验 OCR 证据：`page + parts` 必须逐块出现在 `ocr/pages.jsonl` 的页文本里；通过后标“页级·OCR”。
- Excel 里紫色 = 页级·OCR；红色 = 无定位。

B59 实测：RapidOCR 在第 5 页封面识别出“国之脊梁”“中国院士的科学人生百年”，与书目库一致 → A 类，自动采用，标紫。

## 8. 商用边界（必须写进合同/说明）

1. OCR 是概率识别，不承诺 100%；A 类靠交叉校验，B 类抽样复核，C 类人工。
2. OCR 文本不能直接叫“逐字原文”；证据里必须带 `source=ocr`、引擎/版本、页码/bbox、置信度。
3. 私有化：离线、模型可替换、不依赖云；SaaS：GPU/CPU worker 池、租户隔离、按页计费。
4. 客户书不用于训练；页面图和 OCR 文本的保留/删除策略要可配置。
5. 引擎/模型版本要 pin 住；换版本要重跑并保留旧证据，不能悄悄覆盖。
6. 手写、艺术字、印章、复杂表格、严重倾斜不承诺；走 C 类人工或 VLM 增强。

## 9. 已知限制 / 下一步

- 竖排多栏的阅读顺序目前用“从右到左、从上到下”的规则排序；复杂版面需要 PP-Structure/版面模型。
- 整本页级路由已留接口，但「图片多、图注多」的书需要版面分析，不是纯 OCR 能解决。
- 表格/公式/图注建议单独成类，不硬塞正文段。
- VLM 可作为封面/难页的第二路校验或字段抽取，但不替代整本 OCR。
- 金标准集（扫描/竖排/绘本/表格）和 CER/阅读顺序指标还没建；商用前必须补。

## 10. 测试

```bash
cd platform/engine
python -m unittest discover -s ocr/tests -v
```

测试不加载模型，CI 可直接跑；模型推理用 Docker 或样例页做集成测试。
