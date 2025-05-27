# -*- coding: utf-8 -*-
import os
from PIL import Image, ImageFile, UnidentifiedImageError
from datetime import datetime
import traceback
from typing import Optional, Tuple, Dict, Any
import math

import config

ImageFile.LOAD_TRUNCATED_IMAGES = True

# --- Funções Auxiliares ---

def _decode_exif_string(value: bytes) -> str:
    """Tenta decodificar um valor EXIF bytes para string (UTF-8 luego Latin-1)."""
    try:
        return value.decode('utf-8', 'strict').strip()
    except UnicodeDecodeError:
        try:
            return value.decode('latin-1', 'replace').strip()
        except Exception: # pylint: disable=broad-except
            return repr(value)

def _decode_bytes_aggressively_for_debug(
    byte_string: Optional[bytes],
    tag_name_hint: str = ""
) -> Optional[str]:
    """Función de ayuda para decodificar bytes para logs de depuración."""
    if not isinstance(byte_string, bytes):
        return f"(No es bytes, es {type(byte_string)})"
    
    encodings_to_try = ['utf-8', 'latin-1', 'cp1252', 'utf-16-le', 'utf-16', 'ucs-2']
    for enc in encodings_to_try:
        try:
            decoded_value = byte_string.decode(enc, 'strict')
            if enc.startswith('utf-16') or enc == 'ucs-2':
                decoded_value = decoded_value.replace('\x00', '')
            decoded_value = decoded_value.strip()
            if decoded_value:
                return f"(Decodificado como {enc}: '{decoded_value}')"
        except: # pylint: disable=bare-except
            continue
    return f"(Fallaron todas las decodificaciones, repr: {repr(byte_string)})"

def get_exif_data(image_path: str) -> Optional[Tuple[config.ExifData, Optional[int]]]:
    # (Función get_exif_data como en v2.2-debug.1, usando NOME_PERSONALIZADO_TAG_ID para Artist)
    if config.DEBUG_MODE: print(f"\nDEBUG: [get_exif_data] Procesando: {os.path.basename(image_path)}")
    if not os.path.exists(image_path): print(f"\nError: Archivo no encontrado: {image_path}"); return None, None
    exif_data_raw = None; orientation: Optional[int] = None; gps_info_raw = None; exif_data_decoded: config.ExifData = {}
    try:
        with Image.open(image_path) as img_pil:
            if config.DEBUG_MODE: print(f"DEBUG: [get_exif_data] Imagen '{os.path.basename(image_path)}' abierta con Pillow.")
            try:
                exif_data_raw = img_pil.getexif()
                if not exif_data_raw:
                    if config.DEBUG_MODE: print(f"DEBUG: [get_exif_data] Pillow: No hay datos EXIF.")
            except Exception as e_exif: # pylint: disable=broad-except
                if isinstance(e_exif, (AttributeError, TypeError)) and 'PngImageFile' in str(type(img_pil)):
                    if config.DEBUG_MODE: print("DEBUG: [get_exif_data] Pillow: No hay datos EXIF (PNG).")
                else: print(f"\nWarning: Pillow: No se pudo acceder a los datos EXIF para {os.path.basename(image_path)}: {e_exif}")
            if exif_data_raw:
                if config.DEBUG_MODE: print(f"DEBUG: [get_exif_data] Pillow: Datos EXIF crudos obtenidos.")
                orientation = exif_data_raw.get(config.ORIENTATION_TAG_ID)
                try:
                    if config.GPS_IFD_TAG_ID is not None: gps_info_raw = exif_data_raw.get_ifd(config.GPS_IFD_TAG_ID)
                except Exception: gps_info_raw = None # pylint: disable=broad-except
                raw_date = exif_data_raw.get(config.DATETIME_ORIGINAL_TAG_ID) or exif_data_raw.get(config.DATETIME_TAG_ID)
                date_str = None
                if isinstance(raw_date, str):
                    clean_date = raw_date.replace('\x00', '').strip()
                    try: datetime.strptime(clean_date, '%Y:%m:%d %H:%M:%S'); date_str = clean_date
                    except ValueError: print(f"\nWarning: Pillow: Formato de fecha inválido '{clean_date}' en {os.path.basename(image_path)}")
                exif_data_decoded['DateTimeOriginal'] = date_str
                raw_desc = exif_data_raw.get(config.IMAGE_DESCRIPTION_TAG_ID)
                description = None
                if isinstance(raw_desc, str): description = raw_desc.strip()
                elif isinstance(raw_desc, bytes): description = _decode_exif_string(raw_desc)
                exif_data_decoded['ImageDescription'] = description
                raw_custom_name = exif_data_raw.get(config.NOME_PERSONALIZADO_TAG_ID) # Usa el nuevo ID
                custom_name_str = None
                if isinstance(raw_custom_name, str): custom_name_str = raw_custom_name.strip()
                elif isinstance(raw_custom_name, bytes): custom_name_str = _decode_exif_string(raw_custom_name)
                if custom_name_str: exif_data_decoded[config.PHOTO_INFO_CUSTOM_NAME_KEY] = custom_name_str
                else: exif_data_decoded[config.PHOTO_INFO_CUSTOM_NAME_KEY] = None
                if config.DEBUG_MODE: print(f"DEBUG: [get_exif_data] Nome Personalizado (Tag {config.NOME_PERSONALIZADO_TAG_ID}) leído: '{exif_data_decoded.get(config.PHOTO_INFO_CUSTOM_NAME_KEY)}'")
                skip_tags_values = [config.GPS_IFD_TAG_ID, config.ORIENTATION_TAG_ID, config.IMAGE_DESCRIPTION_TAG_ID,
                                    config.DATETIME_ORIGINAL_TAG_ID, config.DATETIME_TAG_ID, config.NOME_PERSONALIZADO_TAG_ID]
                skip_tags = set(filter(None, skip_tags_values))
                for tag_id, value in exif_data_raw.items():
                    if tag_id in skip_tags or tag_id is None: continue
                    tag_name = config.TAGS.get(tag_id, f"Unknown_{tag_id}")
                    if isinstance(value, bytes):
                        decoded_value = _decode_exif_string(value)
                        if len(decoded_value) > 100 and decoded_value.startswith("b'"): exif_data_decoded[tag_name] = (f"<Binary data length {len(value)}>")
                        else: exif_data_decoded[tag_name] = decoded_value
                    elif isinstance(value, str): exif_data_decoded[tag_name] = value.strip()
                    else: exif_data_decoded[tag_name] = value
                if gps_info_raw:
                    gps_data: Dict[str, Any] = {}
                    # ... (lógica de procesamiento de GPS como estaba)
                    for gps_id, gps_val in gps_info_raw.items():
                        if gps_id is None: continue
                        gps_name = config.GPSTAGS.get(gps_id, f"UnknownGPS_{gps_id}")
                        if isinstance(gps_val, bytes):
                            try: decoded_gps = gps_val.decode('ascii', 'strict').strip()
                            except UnicodeDecodeError: decoded_gps = _decode_exif_string(gps_val)
                            gps_data[gps_name] = decoded_gps
                        elif isinstance(gps_val, tuple) and gps_val:
                            try:
                                numeric_tuple = tuple(float(getattr(v, 'real', v)) for v in gps_val)
                                if all(math.isfinite(n) for n in numeric_tuple): gps_data[gps_name] = numeric_tuple
                                else:
                                    if config.DEBUG_MODE: print(f"DEBUG: GPS tuple contem não-finitos: {gps_val}")
                                    gps_data[gps_name] = repr(gps_val)
                            except (ValueError, TypeError):
                                if config.DEBUG_MODE: print(f"DEBUG: GPS tuple não numérico: {gps_val}")
                                gps_data[gps_name] = repr(gps_val)
                        elif isinstance(gps_val, (int, float)):
                            if math.isfinite(gps_val): gps_data[gps_name] = float(gps_val)
                            else: gps_data[gps_name] = repr(gps_val)
                        else: gps_data[gps_name] = gps_val
                    if gps_data: exif_data_decoded["GPSInfo"] = gps_data
            if not exif_data_raw and orientation is None :
                 if not any(exif_data_decoded.values()):
                    if config.DEBUG_MODE: print("DEBUG: [get_exif_data] No se pudo obtener EXIF ni datos significativos.")
                    return {}, None
            return exif_data_decoded, orientation
    except FileNotFoundError: print(f"\nError: Archivo no encontrado (principal): {image_path}"); return None, None
    except UnidentifiedImageError: print(f"\nError: No se pudo identificar el archivo como imagen válida: {os.path.basename(image_path)}"); return None, None
    except OSError as e: print(f"\nError de Sistema/Archivo leyendo imagen {os.path.basename(image_path)}: {e}"); return None, None
    except Exception as e: # pylint: disable=broad-except
        print(f"\nError inesperado leyendo imagen {os.path.basename(image_path)}: {e}")
        if config.DEBUG_MODE: traceback.print_exc()
        return None, None
