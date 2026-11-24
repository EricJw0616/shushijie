# 第三方组件与许可证（OCR 子系统）

商用前请法务按实际锁定的版本复核；以下是本项目使用的直接依赖及常见许可证：

| 组件 | 用途 | 许可证（以实际版本为准） |
|---|---|---|
| RapidOCR (rapidocr-onnxruntime) | OCR 推理封装 | Apache-2.0 |
| PP-OCR 模型（ch_PP-OCRv4_det / ch_ppocr_mobile_v2.0_cls / ch_PP-OCRv4_rec） | 检测/方向/识别 | Apache-2.0（随 RapidOCR 分发，需保留 NOTICE） |
| ONNX Runtime | 推理运行时 | MIT |
| pypdfium2 / PDFium | PDF 渲染与文字层 | Apache-2.0 / BSD-3-Clause（PDFium） |
| Pillow | 图像读写 | HPND |
| OpenCV | 图像预处理 | Apache-2.0 |
| NumPy | 数值计算 | BSD-3-Clause |

注意：

1. 不要用 PyMuPDF 做商用渲染：它是 AGPL-3.0，SaaS/私有化交付需要商业许可；本项目用 pypdfium2 规避。
2. 模型权重和代码可能适用不同许可证；升级版本时重新核对 NOTICE。
3. 云 OCR 的服务条款、数据保留、跨境传输要单独审，不要只看“能调通”。
4. 客户图书的版权、OCR 复制件的存储/删除、是否用于训练，必须在合同里写清。
