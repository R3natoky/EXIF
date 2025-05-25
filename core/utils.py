# -*- coding: utf-8 -*-
import re
from PIL import Image
from typing import Optional

import config # For config.DEBUG_MODE

def sanitize_filename(name: str) -> str:
    # (Función sin cambios recientes, pero incluida por completitud)
    name = re.sub(r'[\\/*?:"<>|]', "", name); name = name.replace(' ', '_'); return name[:100]

def apply_orientation(image: Image.Image, orientation: Optional[int]) -> Image.Image:
    # (Función sin cambios recientes, pero incluida por completitud)
    actions = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
               5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
    transpose_action = actions.get(orientation)
    if not transpose_action: return image
    original_mode = image.mode
    try:
        if config.DEBUG_MODE: print(f"DEBUG: [apply_orientation] Aplicando orientação {orientation} ({transpose_action.name})") # type: ignore
        oriented_image = image.transpose(transpose_action)
        if oriented_image.mode != original_mode and original_mode not in ('P', 'LA'):
            if config.DEBUG_MODE: print(f"DEBUG: [apply_orientation] Modo mudou de {original_mode} para {oriented_image.mode}, tentando reverter para RGB/RGBA")
            try:
                if 'A' in oriented_image.mode: oriented_image = oriented_image.convert('RGBA')
                else: oriented_image = oriented_image.convert('RGB')
            except Exception as e_conv: print(f"\nWarning: Falha ao reconverter modo após orientação: {e_conv}"); return image # pylint: disable=broad-except
        return oriented_image
    except Exception as e: print(f"\nWarning: Falha ao aplicar orientação EXIF {orientation}: {e}"); return image # pylint: disable=broad-except
