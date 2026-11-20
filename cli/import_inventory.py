#!/usr/bin/env python3
"""Import inventory screenshots from a folder."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps, UnidentifiedImageError

from inventory_grid import contact_sheet, detect, extract_cards, full_screen_grid


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


def import_screenshot(source, destination, cards):
    try:
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
    except UnidentifiedImageError:
        return {'file': source.name, 'card_count': 0, 'error': 'Unsupported or corrupt image.'}
    except OSError as error:
        return {'file': source.name, 'card_count': 0, 'error': error.strerror or str(error)}
    except (ValueError, Image.DecompressionBombError) as error:
        return {'file': source.name, 'card_count': 0, 'error': str(error)}

    grid = full_screen_grid(image)
    if grid is None:
        _, x_lines, y_lines, _ = detect(image)
    else:
        x_lines, y_lines = grid

    start = len(cards)
    for card in extract_cards(image, x_lines, y_lines, full_screen=grid is not None):
        path = f'cards/card-{len(cards) + 1:04d}.png'
        card.image.save(destination / path)
        cards.append({
            'file': path,
            'source': source.name,
            'row': card.row,
            'column': card.column,
            'bounds': card.bounds,
        })

    result = {
        'file': source.name,
        'width': image.width,
        'height': image.height,
        'detector': 'full-screen' if grid is not None else 'projection',
        'rows': len(y_lines) - 1,
        'columns': len(x_lines) - 1,
        'card_count': len(cards) - start,
    }
    if not result['card_count']:
        result['error'] = 'No inventory cards detected.'
    return result


def batch_import(sources, output):
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.inventory-', dir=output.parent) as temporary:
        destination = Path(temporary) / 'result'
        (destination / 'cards').mkdir(parents=True)
        cards = []
        result = [import_screenshot(source, destination, cards) for source in sources]
        for item in result:
            if 'error' in item:
                print(f"{item['file']}: {item['error']}", file=sys.stderr)

        if not cards:
            raise ValueError('No cards imported.')

        def load_cards():
            for card in cards:
                with Image.open(destination / card['file']) as image:
                    yield image

        contact_sheet(load_cards(), len(cards)).save(destination / 'contact-sheet.png')
        manifest = {
            'version': 1,
            'contact_sheet': 'contact-sheet.png',
            'sources': result,
            'cards': cards,
        }
        (destination / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
        )
        destination.rename(output)
    return len(cards), result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='folder containing JPEG, PNG, or WebP screenshots')
    parser.add_argument('-o', '--output', type=Path, required=True, help='new directory for the import')
    args = parser.parse_args(argv)
    try:
        sources = sorted(
            (path for path in args.folder.iterdir()
             if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
            key=lambda path: (path.name.casefold(), path.name),
        )
        if not sources:
            raise ValueError(f'No JPEG, PNG, or WebP images found in {args.folder}.')
        count, result = batch_import(sources, args.output)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    successful = sum(item['card_count'] > 0 for item in result)
    print(f'Imported {count} cards from {successful}/{len(result)} screenshots into {args.output}.')
    return 0 if successful == len(result) else 1


if __name__ == '__main__':
    sys.exit(main())
