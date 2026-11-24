"""Stream local text recognition for selected physical PDF pages."""
from contextlib import closing
import json
import os
import sys
import tempfile

import pypdfium2 as pdfium

from .rapid_provider import RapidOCRProvider


def main(path):
    pages = json.load(sys.stdin)
    engine = RapidOCRProvider(intra_op_num_threads=2, inter_op_num_threads=1)
    with pdfium.PdfDocument(path) as document, tempfile.TemporaryDirectory(prefix='book-pdf-ocr-') as tmp:
        image_path = os.path.join(tmp, 'page.png')
        for number in pages:
            result = {'page': number}
            try:
                with closing(document[number - 1]) as page:
                    scale = min(200 / 72, 3200 / max(page.get_size()))
                    with closing(page.render(scale=scale)) as bitmap:
                        image = bitmap.to_pil()
                        width, height = image.size
                        if image.convert('L').getextrema()[0] >= 250:
                            print(json.dumps({'page': number, 'blank': True}), flush=True)
                            continue
                        image.save(image_path)
                result['lines'] = [{'text': line.text, 'score': line.score,
                                    'box': [line.bbox[0]/width, line.bbox[1]/height,
                                            line.bbox[2]/width, line.bbox[3]/height]}
                                   for line in engine.recognize(image_path, page=number)]
            except Exception:
                result['failed'] = True
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
