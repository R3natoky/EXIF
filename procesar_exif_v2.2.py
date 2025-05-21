# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Script para extraer coordenadas (Lat/Lon, UTM) y fecha de fotos EXIF.
# Genera archivos KMZ, CSV, Excel o KML simple. Optimiza tamaño para Excel.
# v2.2: Funcionalidad "Nome Personalizado" implementada usando tag 'Artist' (ID 315).
#       Título de placemark KML/KMZ prioriza Nome Personalizado.
#       Limpieza de código y logs de depuración.
# -----------------------------------------------------------------------------

import os
from PIL import Image, ImageFile, UnidentifiedImageError
import simplekml
import pandas as pd
import re
import math
import pyproj
from datetime import datetime
import io
import tempfile
import shutil
import traceback
from typing import Optional, Dict, Any, Tuple, List, Union

import config # Importa nuestro módulo de configuración

ImageFile.LOAD_TRUNCATED_IMAGES = True

# --- Dependência para Opção 4 ---
try:
    import piexif
except ImportError:
    print("ERROR: La librería 'piexif' es necesaria para la opción 4 "
          "(Actualizar EXIF).")
    print("Por favor, instálala ejecutando: pip install piexif")
    piexif = None # type: ignore

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

def dms_to_decimal(
    degrees: config.Number,
    minutes: config.Number,
    seconds: config.Number,
    direction: str
) -> float:
    """
    Convierte Grados, Minutos, Segundos (DMS) a Grados Decimales.
    Lança ValueError em caso de erro de conversão ou direção inválida.
    """
    try:
        deg_f = float(getattr(degrees, 'real', degrees))
        min_f = float(getattr(minutes, 'real', minutes))
        sec_f = float(getattr(seconds, 'real', seconds))

        if not all(math.isfinite(x) for x in [deg_f, min_f, sec_f]):
            raise ValueError(
                f"Componente(s) DMS no finito: D={degrees}, M={minutes}, S={seconds}"
            )
        if not (0 <= min_f < 60 and 0 <= sec_f < 60):
            print(
                f"\nWarning: Valores DMS fuera del range (Min={min_f}, Sec={sec_f}), "
                "continuando cálculo."
            )
        dd = deg_f + min_f / 60.0 + sec_f / 3600.0
        direction_upper = direction.upper()
        if direction_upper in ['S', 'W']:
            return -dd
        if direction_upper in ['N', 'E']:
            return dd
        raise ValueError(f"Dirección GPS desconocida: '{direction}'")
    except (ValueError, TypeError, AttributeError) as e:
        raise ValueError(
            f"Error convirtiendo DMS ({degrees}, {minutes}, {seconds}, {direction}): {e}"
        ) from e

def get_coordinates(exif_data: config.ExifData) -> config.Coordinates:
    # (Función sin cambios recientes, pero incluida por completitud)
    # ... (Código completo de get_coordinates de la v2.1-alpha.5 / v2.2-debug.1) ...
    if not exif_data or "GPSInfo" not in exif_data: return None
    gps = exif_data["GPSInfo"]
    lat_dms = gps.get("GPSLatitude"); lat_ref = gps.get("GPSLatitudeRef"); lon_dms = gps.get("GPSLongitude"); lon_ref = gps.get("GPSLongitudeRef")
    if not (lat_dms and lat_ref and lon_dms and lon_ref):
        if config.DEBUG_MODE: print("DEBUG: [get_coordinates] Faltan tags GPS esenciales.")
        return None
    if not isinstance(lat_ref, str) or not isinstance(lon_ref, str):
        if config.DEBUG_MODE: print(f"DEBUG: [get_coordinates] Refs GPS no son strings: LatRef={type(lat_ref)}, LonRef={type(lon_ref)}")
        return None
    if not isinstance(lat_dms, tuple) or len(lat_dms) != 3:
        if config.DEBUG_MODE: print(f"DEBUG: [get_coordinates] Lat DMS inválido: {lat_dms}")
        return None
    if not isinstance(lon_dms, tuple) or len(lon_dms) != 3:
        if config.DEBUG_MODE: print(f"DEBUG: [get_coordinates] Lon DMS inválido: {lon_dms}")
        return None
    try:
        _ = [float(getattr(v, 'real', v)) for v in lat_dms]; _ = [float(getattr(v, 'real', v)) for v in lon_dms]
    except (ValueError, TypeError):
        if config.DEBUG_MODE: print(f"DEBUG: [get_coordinates] Conteúdo DMS não numérico: LAT={lat_dms}, LON={lon_dms}")
        return None
    try:
        latitude = dms_to_decimal(lat_dms[0], lat_dms[1], lat_dms[2], lat_ref); longitude = dms_to_decimal(lon_dms[0], lon_dms[1], lon_dms[2], lon_ref)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180): print(f"\nWarning: Coordenadas calculadas fuera de rango: Lat={latitude:.7f}, Lon={longitude:.7f}"); return None
        return latitude, longitude
    except ValueError as e: print(f"\nError procesando coordenadas DMS: {e}"); return None
    except Exception as e_gen: # pylint: disable=broad-except
        if config.DEBUG_MODE: traceback.print_exc()
        print(f"\nError inesperado en get_coordinates: {e_gen}"); return None

def convert_to_utm(latitude: float, longitude: float) -> config.UTMCoordinates:
    # (Función sin cambios recientes, pero incluida por completitud)
    # ... (Código completo de convert_to_utm de la v2.1-alpha.5 / v2.2-debug.1) ...
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)): print(f"\nError UTM: Latitud/Longitud no numérica ({type(latitude)}, {type(longitude)})"); return None, None, None, None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180): print(f"\nError UTM: Coordenadas Lat/Lon fuera de rango ({latitude}, {longitude})"); return None, None, None, None
    epsg_code = 0 
    try:
        zone = math.floor((longitude + 180) / 6) + 1; hemisphere = 'N' if latitude >= 0 else 'S'
        epsg_code_base = 32600 if latitude >= 0 else 32700; epsg_code = epsg_code_base + zone
        crs_wgs84 = pyproj.CRS("EPSG:4326"); crs_utm = pyproj.CRS(f"EPSG:{epsg_code}")
        transformer = pyproj.Transformer.from_crs(crs_wgs84, crs_utm, always_xy=True)
        easting, northing = transformer.transform(longitude, latitude)
        if not math.isfinite(easting) or not math.isfinite(northing): raise ValueError(f"Resultado da transformação UTM não finito: E={easting}, N={northing}")
        return easting, northing, zone, hemisphere
    except pyproj.exceptions.CRSError as e_crs:
        epsg_str = f"EPSG:{epsg_code}" if epsg_code != 0 else "EPSG desconocido"
        print(f"\nError UTM: Problema com o sistema de coordenadas ({epsg_str}): {e_crs}"); return None, None, None, None
    except ValueError as e_val: print(f"\nError UTM: Problema nos valores durante a conversão: {e_val}"); return None, None, None, None
    except Exception as e: # pylint: disable=broad-except
        if config.DEBUG_MODE: traceback.print_exc()
        print(f"\nError inesperado en la conversión UTM para ({latitude}, {longitude}): {e}"); return None, None, None, None

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

# ... (Resto de las funciones: get_exif_data, update_exif_from_excel, _generate_excel,
#      _generate_kmz, _generate_csv, _generate_kml_simple, process_folder, y el bloque __main__
#      deben ser copiadas de la versión v2.2-debug.1 que te proporcioné anteriormente,
#      la cual ya contenía las correcciones para Pylance y la lógica de Artist.
#      Solo asegúrate de que el número de versión en el print de __main__ sea v2.2)

# Para asegurar la completitud, pegaré el script completo desde este punto,
# basándome en la última versión funcional (v2.2-debug.1),
# y solo ajustando el número de versión final y limpiando logs de depuración muy específicos.

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

def update_exif_from_excel(excel_path: str, image_folder_path: str) -> None:
    # (Función update_exif_from_excel como en v2.2-debug.1)
    if piexif is None: print("\nERROR: La librería 'piexif' no está instalada."); return
    print("\n--- Actualizando Descripciones y Nomes Personalizados (Artist) EXIF desde Excel ---")
    print(f"Archivo Excel: {excel_path}"); print(f"Carpeta de Imágenes: {image_folder_path}")
    print("\nIMPORTANTE: Esta operación modificará los archivos de imagen originales.")
    confirm_raw = input("¿Desea continuar? (S/n): ").strip()
    if confirm_raw.lower() == 'n': print("Operación cancelada."); return
    if not os.path.isfile(excel_path): print(f"\nError: Archivo Excel no encontrado: {excel_path}"); return
    if not os.path.isdir(image_folder_path): print(f"\nError: Carpeta de imágenes no encontrada: {image_folder_path}"); return
    updated_count, skipped_no_data, skipped_no_file = 0, 0, 0
    error_read_excel, error_exif_update, total_rows = 0, 0, 0
    NOME_PERSONALIZADO_COL_NAME = 'NomePersonalizado (Editable)'; DESCRIPCION_COL_NAME = 'Descripcion (EXIF)'
    try:
        df = None; print(f"\nLeyendo archivo Excel '{os.path.basename(excel_path)}'...")
        try: df = pd.read_excel(excel_path, sheet_name='Coordenadas_UTM_Data'); print("  -> Hoja 'Coordenadas_UTM_Data' leída.")
        except ValueError:
            try: print("  -> Hoja 'Coordenadas_UTM_Data' no encontrada, intentando primera hoja..."); df = pd.read_excel(excel_path, sheet_name=0); print("  -> Primera hoja leída.")
            except Exception as read_generic_err: print(f"\nError: No se pudo leer Excel: {read_generic_err}"); error_read_excel += 1; return
        except Exception as read_sheet_err: print(f"\nError al leer la hoja: {read_sheet_err}"); error_read_excel += 1; return
        if df is None: print("\nError: No se cargaron datos del Excel."); return
        if 'filename' not in df.columns: print(f"\nError: Excel debe tener columna 'filename'. Columnas: {list(df.columns)}"); return
        for col_name in [NOME_PERSONALIZADO_COL_NAME, DESCRIPCION_COL_NAME]:
            if col_name not in df.columns: print(f"\nAdvertencia: Columna '{col_name}' no encontrada en Excel.")
        total_rows = len(df)
        print(f"Procesando {total_rows} filas del Excel para actualizar EXIF...")
        for index, row in df.iterrows():
            current_row_num = index + 2; filename_raw = row.get('filename'); description_raw = row.get(DESCRIPCION_COL_NAME); custom_name_raw = row.get(NOME_PERSONALIZADO_COL_NAME)
            if pd.isna(filename_raw) or not isinstance(filename_raw, str) or not filename_raw.strip():
                if config.DEBUG_MODE: print(f"DEBUG: Fila {current_row_num} omitida (filename inválido)")
                continue
            filename = filename_raw.strip(); image_path = os.path.join(image_folder_path, filename)
            description_str_to_write = ""
            if not pd.isna(description_raw):
                if isinstance(description_raw, (int, float)): description_str_to_write = str(description_raw).strip()
                elif isinstance(description_raw, str): description_str_to_write = description_raw.strip()
            custom_name_str_to_write = ""
            if not pd.isna(custom_name_raw):
                if isinstance(custom_name_raw, (int, float)): custom_name_str_to_write = str(custom_name_raw).strip()
                elif isinstance(custom_name_raw, str): custom_name_str_to_write = custom_name_raw.strip()
            if not description_str_to_write and not custom_name_str_to_write:
                if config.DEBUG_MODE: print(f"DEBUG: Fila {current_row_num} ('{filename}') omitida (sin datos para actualizar).")
                skipped_no_data += 1; continue
            if not os.path.isfile(image_path): print(f"\nWarning: Imagen no encontrada '{filename}', omitiendo."); skipped_no_file += 1; continue
            print(f"\rActualizando {index + 1}/{total_rows}: {filename}...", end='', flush=True)
            try:
                exif_dict = piexif.load(image_path);
                if '0th' not in exif_dict: exif_dict['0th'] = {}
                if description_str_to_write:
                    exif_dict['0th'][piexif.ImageIFD.ImageDescription] = description_str_to_write.encode('utf-8')
                elif piexif.ImageIFD.ImageDescription in exif_dict.get('0th', {}):
                    del exif_dict['0th'][piexif.ImageIFD.ImageDescription]
                if custom_name_str_to_write:
                    exif_dict['0th'][config.NOME_PERSONALIZADO_TAG_ID] = custom_name_str_to_write.encode('utf-8')
                elif config.NOME_PERSONALIZADO_TAG_ID in exif_dict.get('0th', {}):
                    del exif_dict['0th'][config.NOME_PERSONALIZADO_TAG_ID]
                if config.DEBUG_MODE:
                    try:
                        temp_exif_bytes_debug = piexif.dump(exif_dict)
                        reloaded_temp_debug = piexif.load(temp_exif_bytes_debug)
                        artist_val_debug = reloaded_temp_debug.get("0th", {}).get(config.NOME_PERSONALIZADO_TAG_ID)
                        # Añadido \n para mejor formato si este log se activa
                        print(f"\nDEBUG [update_exif]: Valor 'Artist' en bytes dumpeados para '{filename}': {repr(artist_val_debug)} {_decode_bytes_aggressively_for_debug(artist_val_debug, 'Artist from dumped bytes')}") # type: ignore
                    except Exception as e_debug_dump: print(f"DEBUG [update_exif]: Error depurando dump para {filename}: {e_debug_dump}")
                exif_bytes = piexif.dump(exif_dict); piexif.insert(exif_bytes, image_path); updated_count += 1
            except Exception as e: # pylint: disable=broad-except
                print(f"\nError inesperado actualizando EXIF para '{filename}': {e}")
                if config.DEBUG_MODE: traceback.print_exc()
                error_exif_update += 1
        print()
        print("\n--- Resumen Actualización EXIF ---")
        print(f"  - Filas leídas del Excel: {total_rows}\n  - Imágenes actualizadas: {updated_count}")
        print(f"  - Omitidas (sin datos válidos en Excel): {skipped_no_data}\n  - Omitidas (archivo de imagen no encontrado): {skipped_no_file}")
        print(f"  - Errores leyendo Excel: {error_read_excel}\n  - Errores durante la actualización EXIF: {error_exif_update}")
        print("----------------------------------")
    except Exception as e: # pylint: disable=broad-except
        print(f"\nError fatal durante el proceso de actualización desde Excel: {e}")
        if config.DEBUG_MODE: traceback.print_exc()

def _generate_excel(photo_data_list: List[config.PhotoInfo], out_base: str) -> Tuple[bool, List[str]]:
    # (Función con logs de depuración y usando NOME_PERSONALIZADO_TAG_ID (Artist))
    # Se han limpiado algunos logs de depuración muy específicos, dejando los más útiles.
    if config.DEBUG_MODE: print(f"DEBUG [_generate_excel]: Iniciando con {len(photo_data_list)} elementos.")
    print("\nGenerando Excel con imágenes (puede tardar)...")
    excel_file = f"{out_base}_con_fotos.xlsx"; generated = False; temps_to_delete: List[str] = []
    try:
        df = pd.DataFrame(photo_data_list); df_out = pd.DataFrame()
        if config.DEBUG_MODE: print(f"DEBUG [_generate_excel]: DataFrame inicial 'df' creado con {len(df)} filas.")
        if 'nome' in df.columns: df_out['Nome (Archivo)'] = df['nome'].fillna("").astype(str)
        else: df_out['Nome (Archivo)'] = ""
        if config.PHOTO_INFO_CUSTOM_NAME_KEY in df.columns and df[config.PHOTO_INFO_CUSTOM_NAME_KEY].notna().any():
            df_out['NomePersonalizado (Editable)'] = df[config.PHOTO_INFO_CUSTOM_NAME_KEY].fillna("").astype(str)
        elif 'nome' in df.columns: df_out['NomePersonalizado (Editable)'] = df['nome'].fillna("").astype(str)
        else: df_out['NomePersonalizado (Editable)'] = ""
        if 'description' in df.columns: df_out['Descripcion (EXIF)'] = df['description'].fillna("").astype(str)
        else: df_out['Descripcion (EXIF)'] = ""
        if 'filename' in df.columns: df_out['filename'] = df['filename']
        else: df_out['filename'] = ""
        if 'photo_date' in df.columns: df_out['photo_date'] = df['photo_date']
        if 'utm_easting' in df.columns: df_out['utm_easting'] = df['utm_easting'].apply(lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x)
        if 'utm_northing' in df.columns: df_out['utm_northing'] = df['utm_northing'].apply(lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x)
        if 'utm_zone' in df.columns: df_out['utm_zone'] = df['utm_zone']
        if 'utm_hemisphere' in df.columns: df_out['utm_hemisphere'] = df['utm_hemisphere']
        
        cols_data_order = ['Nome (Archivo)', 'NomePersonalizado (Editable)', 'Descripcion (EXIF)', 'filename', 'photo_date',
                           'utm_easting', 'utm_northing', 'utm_zone', 'utm_hemisphere']
        final_cols_data = [col for col in cols_data_order if col in df_out.columns]
        if config.DEBUG_MODE: print(f"DEBUG [_generate_excel]: df_out columnas antes de reordenar: {list(df_out.columns)}")
        df_out = df_out[final_cols_data] # Reordenar y seleccionar columnas finales
        if config.DEBUG_MODE: print(f"DEBUG [_generate_excel]: df_out columnas después de reordenar: {list(df_out.columns)}. Filas: {len(df_out)}")
        
        if df_out.empty and not df.empty : # Solo advertir si el df original no estaba vacío
             if config.DEBUG_MODE: print("DEBUG [_generate_excel]: ADVERTENCIA - df_out está vacío, pero el DataFrame original tenía datos. El Excel estará vacío de datos textuales.")
        elif df_out.empty and df.empty:
             if config.DEBUG_MODE: print("DEBUG [_generate_excel]: df_out y df original están vacíos. El Excel solo tendrá cabeceras (si se escriben).")


        with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
            df_out.to_excel(writer, sheet_name='Coordenadas_UTM_Data', startcol=config.EXCEL_DATA_START_COL, index=False)
            if config.DEBUG_MODE: print("DEBUG [_generate_excel]: Datos textuales escritos en Excel.")
            workbook = writer.book; worksheet = writer.sheets['Coordenadas_UTM_Data']
            worksheet.set_column(config.EXCEL_IMAGE_COL, config.EXCEL_IMAGE_COL, config.EXCEL_TARGET_IMAGE_WIDTH_PX * config.EXCEL_COL_WIDTH_FACTOR)
            current_col_idx = config.EXCEL_DATA_START_COL
            # Ajustar anchos de columnas de datos
            col_widths = {'Nome (Archivo)': 25, 'NomePersonalizado (Editable)': 30, 'Descripcion (EXIF)': 40, 'filename': 30}
            for i, col_name in enumerate(final_cols_data):
                worksheet.set_column(current_col_idx + i, current_col_idx + i, col_widths.get(col_name, 15)) # 15 por defecto

            total = len(df) # df original para iterar sobre imágenes
            print("  -> Insertando imágenes en Excel...")
            for idx, row_data in df.iterrows():
                # ... (lógica de inserción de imágenes como en v2.2-debug.1) ...
                filename = row_data.get('filename', 'N/A'); filepath = row_data.get('filepath'); orientation = row_data.get('orientation')
                excel_row_index = idx + 1
                print(f"\r     {idx + 1}/{total}: {filename[:40]}...", end='', flush=True)
                if not filepath or not os.path.exists(filepath):
                    print(f"\n     Skipping image for row {excel_row_index}: File not found '{filepath}'"); worksheet.set_row(excel_row_index, 15); continue
                temp_img_path_excel = None; processed_image = None
                try:
                    with Image.open(filepath) as img_orig:
                        img_oriented = apply_orientation(img_orig, orientation); processed_image = img_oriented.copy()
                    w_orig, h_orig = processed_image.size
                    if w_orig == 0 or h_orig == 0: raise ValueError("Dimensões inválidas da imagem.")
                    thumb_w = int(config.EXCEL_TARGET_IMAGE_WIDTH_PX * config.EXCEL_TEMP_IMAGE_SCALE_FACTOR)
                    thumb_h_calc = int(h_orig * (thumb_w / w_orig))
                    processed_image.thumbnail((thumb_w, thumb_h_calc * 2), Image.Resampling.LANCZOS)
                    final_w, final_h = processed_image.size
                    scale_factor = config.EXCEL_TARGET_IMAGE_WIDTH_PX / final_w
                    row_height = (final_h * scale_factor) * config.EXCEL_ROW_HEIGHT_FACTOR + 5
                    worksheet.set_row(excel_row_index, row_height)
                    save_format = 'JPEG'; save_suffix = '.jpg'; save_options_excel: Dict[str, Any] = {'quality': config.EXCEL_TEMP_IMAGE_QUALITY}
                    if processed_image.mode in ('P', 'LA', 'RGBA'):
                        save_format = 'PNG'; save_suffix = '.png'; save_options_excel = {'optimize': True}
                        if processed_image.mode in ('P', 'LA'):
                            try:
                                if config.DEBUG_MODE: print(f" [Convertendo {processed_image.mode} para RGBA]", end="")
                                processed_image = processed_image.convert("RGBA")
                            except Exception as conv_e: print(f"\n     Warning: Falha ao converter {processed_image.mode}->RGBA para {filename}: {conv_e}")
                    elif processed_image.mode == 'CMYK':
                        try:
                            if config.DEBUG_MODE: print(" [Convertendo CMYK para RGB]", end="")
                            processed_image = processed_image.convert("RGB")
                            save_format = 'JPEG'; save_suffix = '.jpg'; save_options_excel = {'quality': config.EXCEL_TEMP_IMAGE_QUALITY}
                        except Exception as conv_e: print(f"\n     Warning: Falha ao converter CMYK->RGB para {filename}: {conv_e}"); raise ValueError(f"Não foi possível converter CMYK para {filename}")
                    with tempfile.NamedTemporaryFile(delete=False, suffix=save_suffix, prefix="excel_") as tf:
                        temp_img_path_excel = tf.name
                        processed_image.save(tf, format=save_format, **save_options_excel)
                    if temp_img_path_excel and os.path.exists(temp_img_path_excel):
                        temps_to_delete.append(temp_img_path_excel)
                        insert_options = {'x_scale': scale_factor, 'y_scale': scale_factor, 'object_position': 1}
                        worksheet.insert_image(excel_row_index, config.EXCEL_IMAGE_COL, temp_img_path_excel, insert_options)
                except UnidentifiedImageError: print(f"\n     Warning: No se pudo identificar {filename} como imagen para Excel."); worksheet.set_row(excel_row_index, 15)
                except ValueError as ve: print(f"\n     Warning: Error de valor procesando imagen {filename} para Excel: {ve}"); worksheet.set_row(excel_row_index, 15)
                except Exception as img_e: # pylint: disable=broad-except
                    print(f"\n     Error procesando imagen {filename} para Excel (fila {excel_row_index}): {img_e}")
                    if processed_image: processed_image.close(); worksheet.set_row(excel_row_index, 15)
                finally:
                    if processed_image:
                        try: processed_image.close()
                        except Exception: pass # pylint: disable=broad-except
            print()
        if config.DEBUG_MODE: print(f"DEBUG [_generate_excel]: pd.ExcelWriter cerrado. Archivo debería estar guardado.")
        print(f"\nArchivo Excel guardado con éxito: {os.path.abspath(excel_file)}"); generated = True
    except Exception as e: # pylint: disable=broad-except
        print(f"\nERROR FATAL generando archivo Excel: {e}")
        if config.DEBUG_MODE: traceback.print_exc()
    if config.DEBUG_MODE: print(f"DEBUG [_generate_excel]: Finalizando. Generated: {generated}")
    return generated, temps_to_delete

# _generate_kmz, _generate_csv, _generate_kml_simple
# (Estas funciones se copiaron de v2.1-alpha.5 / v2.2-debug.1 y ya tienen la lógica de placemark actualizada para Artist)
def _generate_kmz(photo_data_list: List[config.PhotoInfo], folder_name: str, out_base: str) -> Tuple[bool, List[str]]:
    kml = simplekml.Kml(name=f"Coords {folder_name}") # type: ignore
    print("\nGenerando KMZ (Google Earth)..."); total = len(photo_data_list); temps_to_delete: List[str] = []; generated = False; skipped_coords = 0
    for idx, data in enumerate(photo_data_list):
        filename = data['filename']
        print(f"\r  -> Procesando KMZ {idx + 1}/{total}: {filename[:40]}...", end="", flush=True)
        lat = data.get('latitude'); lon = data.get('longitude')
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))): print(f"\n   Skipping {filename}: Coordenadas inválidas ({lat}, {lon})"); skipped_coords += 1; continue
        custom_name = data.get(config.PHOTO_INFO_CUSTOM_NAME_KEY); description_exif = data.get('description'); filename_original = data.get('filename')
        if config.DEBUG_MODE:
            print(f"\nDEBUG [Placemark Name Logic for {filename_original}]:")
            print(f"  - Custom Name (Tag {config.NOME_PERSONALIZADO_TAG_ID}): '{custom_name}' (Tipo: {type(custom_name)})")
            print(f"  - Description EXIF: '{description_exif}' (Tipo: {type(description_exif)})")
        final_point_name = ""
        if custom_name and custom_name.strip(): final_point_name = custom_name.strip()
        elif description_exif and description_exif.strip():
            lines = description_exif.splitlines();
            for line in lines:
                stripped_line = line.strip()
                if stripped_line: final_point_name = stripped_line; break
        if not final_point_name: final_point_name = filename_original if filename_original else 'Punto Desconocido'
        if config.DEBUG_MODE: print(f"  - Final Placemark Name for KMZ: '{final_point_name}'")
        pnt = kml.newpoint(name=final_point_name, coords=[(lon, lat)]) # type: ignore
        if data.get("photo_date"):
            try: dt = datetime.strptime(data['photo_date'], '%Y:%m:%d %H:%M:%S'); pnt.timestamp.when = dt.strftime('%Y-%m-%dT%H:%M:%SZ') # type: ignore
            except (ValueError, TypeError): pass
        desc_html_parts = []
        custom_name_val = data.get(config.PHOTO_INFO_CUSTOM_NAME_KEY); nome_archivo_val = data.get('nome'); description_val = data.get('description')
        if custom_name_val: desc_html_parts.append(f"<b>Nome Personalizado (Artist):</b> {custom_name_val}")
        if nome_archivo_val: desc_html_parts.append(f"<b>Nome (Archivo):</b> {nome_archivo_val}")
        if description_val: desc_html_parts.append(f"<b>Descripción (EXIF):</b> {description_val}")
        desc_html_parts.append(f"<b>Archivo:</b> {data.get('filename', 'N/A')}"); desc_html_parts.append(f"<b>Data:</b> {data.get('photo_date', 'N/A')}")
        utm_e_val = data.get('utm_easting'); utm_n_val = data.get('utm_northing')
        utm_e = f"{utm_e_val:.2f}" if isinstance(utm_e_val, (int, float)) else 'N/A'; utm_n = f"{utm_n_val:.2f}" if isinstance(utm_n_val, (int, float)) else 'N/A'
        utm_z = data.get('utm_zone', 'N/A'); utm_h = data.get('utm_hemisphere', '')
        desc_html_parts.append(f"<b>UTM:</b> Zona {utm_z}{utm_h}, E: {utm_e}, N: {utm_n}")
        img_path = data.get('filepath'); orientation = data.get('orientation')
        temp_img_path = None; img_ref_in_kml = None; img_copy_kmz = None
        if img_path and os.path.exists(img_path):
            try:
                with Image.open(img_path) as img_orig:
                    img_oriented = apply_orientation(img_orig, orientation); img_copy_kmz = img_oriented.copy()
                    img_copy_kmz.thumbnail((config.KMZ_IMAGE_WIDTH, config.KMZ_IMAGE_WIDTH * 10), Image.Resampling.LANCZOS)
                    img_format_out = 'JPEG'; save_options_kmz: Dict[str, Any] = {'quality': config.KMZ_IMAGE_QUALITY, 'optimize': True}
                    if img_copy_kmz.mode in ('P', 'RGBA', 'LA'):
                        if config.DEBUG_MODE: print(f" [Convertendo modo {img_copy_kmz.mode} para RGB]", end="")
                        try:
                            background = Image.new("RGB", img_copy_kmz.size, (255, 255, 255))
                            mask = None
                            if 'A' in img_copy_kmz.mode: mask = img_copy_kmz.split()[-1]
                            img_to_paste = img_copy_kmz.convert("RGBA").convert("RGB")
                            background.paste(img_to_paste, (0, 0), mask=mask); img_copy_kmz.close(); img_copy_kmz = background
                        except Exception as e_conv_kmz: print(f"\n   Warning: Falha ao converter imagem {filename} para KMZ: {e_conv_kmz}"); img_copy_kmz.close(); img_copy_kmz = None # type: ignore
                    if img_copy_kmz:
                        suffix = '.jpg'
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="kmz_") as tf:
                            temp_img_path = tf.name; img_copy_kmz.save(tf, format=img_format_out, **save_options_kmz)
                if temp_img_path and os.path.exists(temp_img_path): temps_to_delete.append(temp_img_path); img_ref_in_kml = kml.addfile(temp_img_path) # type: ignore
            except UnidentifiedImageError: print(f"\n   Warning: No se pudo identificar {filename} como imagen para KMZ.")
            except Exception as e_img: print(f"\n   Warning: Error procesando imagen {filename} para KMZ: {e_img}") # pylint: disable=broad-except
            finally:
                if img_copy_kmz:
                    try: img_copy_kmz.close()
                    except Exception: pass # pylint: disable=broad-except
        desc_html = "<br/>".join(desc_html_parts)
        if img_ref_in_kml: desc_html += (f'<hr/><img src="{img_ref_in_kml}" alt="Foto" width="{config.KMZ_IMAGE_WIDTH}" />')
        else: desc_html += '<hr/><i>Imagen no disponible o no embebida.</i>'
        pnt.description = desc_html # type: ignore
    print()
    if skipped_coords > 0: print(f"Aviso: {skipped_coords} puntos omitidos por coordenadas inválidas.")
    kmz_file = f"{out_base}.kmz"
    try: kml.savekmz(kmz_file); print(f"\nArchivo KMZ guardado con éxito: {os.path.abspath(kmz_file)}"); generated = True # type: ignore
    except Exception as e_save: print(f"\nERROR FATAL guardando KMZ {kmz_file}: {e_save}"); traceback.print_exc() # pylint: disable=broad-except
    return generated, temps_to_delete

def _generate_csv(photo_data_list: List[config.PhotoInfo], out_base: str) -> bool:
    print("\nGenerando CSV..."); generated = False
    try:
        df = pd.DataFrame(photo_data_list)
        cols_to_include = ['nome', config.PHOTO_INFO_CUSTOM_NAME_KEY, 'description', 'filename', 'photo_date',
                           'latitude', 'longitude', 'utm_easting', 'utm_northing', 'utm_zone', 'utm_hemisphere']
        cols_in_df = [col for col in cols_to_include if col in df.columns]
        df_csv = df[cols_in_df].copy()
        df_csv.rename(columns={ 'nome': 'Nome (Archivo)', config.PHOTO_INFO_CUSTOM_NAME_KEY: 'Nome Personalizado (Artist)', 'description': 'Descripcion (EXIF)' }, inplace=True)
        for col in ['latitude', 'longitude']:
            if col in df_csv: df_csv[col] = df_csv[col].apply(lambda x: f"{x:.7f}" if isinstance(x, (int, float)) else x)
        for col in ['utm_easting', 'utm_northing']:
            if col in df_csv: df_csv[col] = df_csv[col].apply(lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x)
        csv_file = f"{out_base}.csv"; df_csv.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"\nArchivo CSV guardado con éxito: {os.path.abspath(csv_file)}"); generated = True
    except Exception as e: print(f"\nERROR FATAL generando CSV: {e}"); # pylint: disable=broad-except
    if config.DEBUG_MODE: traceback.print_exc()
    return generated

def _generate_kml_simple(photo_data_list: List[config.PhotoInfo], folder_name: str, out_base: str) -> bool:
    kml = simplekml.Kml(name=f"Coords {folder_name} (Simple)") # type: ignore
    print("\nGenerando KML simple (My Maps)..."); total = len(photo_data_list); generated = False; skipped_coords = 0
    for idx, data in enumerate(photo_data_list):
        filename = data['filename']
        print(f"\r  -> Añadiendo KML simple {idx + 1}/{total}: {filename[:40]}...", end="", flush=True)
        lat = data.get('latitude'); lon = data.get('longitude')
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))): print(f"\n   Skipping {filename}: Coordenadas inválidas ({lat}, {lon})"); skipped_coords += 1; continue
        custom_name = data.get(config.PHOTO_INFO_CUSTOM_NAME_KEY); description_exif = data.get('description'); filename_original = data.get('filename')
        if config.DEBUG_MODE:
            print(f"\nDEBUG [Placemark Name Logic for {filename_original}]:")
            print(f"  - Custom Name (Tag {config.NOME_PERSONALIZADO_TAG_ID}): '{custom_name}' (Tipo: {type(custom_name)})")
            print(f"  - Description EXIF: '{description_exif}' (Tipo: {type(description_exif)})")
        final_point_name = ""
        if custom_name and custom_name.strip(): final_point_name = custom_name.strip()
        elif description_exif and description_exif.strip():
            lines = description_exif.splitlines();
            for line in lines:
                stripped_line = line.strip()
                if stripped_line: final_point_name = stripped_line; break
        if not final_point_name: final_point_name = filename_original if filename_original else 'Punto Desconocido'
        if config.DEBUG_MODE: print(f"  - Final Placemark Name for KML Simple: '{final_point_name}'")
        pnt = kml.newpoint(name=final_point_name, coords=[(lon, lat)]) # type: ignore
        if data.get("photo_date"):
            try: dt = datetime.strptime(data['photo_date'], '%Y:%m:%d %H:%M:%S'); pnt.timestamp.when = dt.strftime('%Y-%m-%dT%H:%M:%SZ') # type: ignore
            except (ValueError, TypeError): pass
        desc_html_parts = []
        custom_name_val = data.get(config.PHOTO_INFO_CUSTOM_NAME_KEY); nome_archivo_val = data.get('nome'); description_val = data.get('description')
        if custom_name_val: desc_html_parts.append(f"<b>Nome Personalizado (Artist):</b> {custom_name_val}")
        if nome_archivo_val: desc_html_parts.append(f"<b>Nome (Archivo):</b> {nome_archivo_val}")
        if description_val: desc_html_parts.append(f"<b>Descripción (EXIF):</b> {description_val}")
        desc_html_parts.append(f"<b>Archivo:</b> {data.get('filename', 'N/A')}"); desc_html_parts.append(f"<b>Data:</b> {data.get('photo_date', 'N/A')}")
        utm_e_val = data.get('utm_easting'); utm_n_val = data.get('utm_northing')
        utm_e = f"{utm_e_val:.2f}" if isinstance(utm_e_val, (int, float)) else 'N/A'; utm_n = f"{utm_n_val:.2f}" if isinstance(utm_n_val, (int, float)) else 'N/A'
        utm_z = data.get('utm_zone', 'N/A'); utm_h = data.get('utm_hemisphere', '')
        desc_html_parts.append(f"<b>UTM:</b> Zona {utm_z}{utm_h}, E: {utm_e}, N: {utm_n}")
        pnt.description = "<br/>".join(desc_html_parts) # type: ignore
    print()
    if skipped_coords > 0: print(f"Aviso: {skipped_coords} puntos omitidos por coordenadas inválidas.")
    kml_file = f"{out_base}_simple.kml"
    try: kml.save(kml_file); print(f"\nArchivo KML simple guardado con éxito: {os.path.abspath(kml_file)}"); generated = True # type: ignore
    except Exception as e: print(f"\nERROR FATAL guardando KML simple {kml_file}: {e}") # pylint: disable=broad-except
    return generated

def process_folder(folder_path: str, output_format: str) -> None:
    if config.DEBUG_MODE: print(f"\nDEBUG [process_folder]: Iniciando para: '{folder_path}', Formato: '{output_format.upper()}'")
    if not os.path.isdir(folder_path): print(f"Error: Carpeta no encontrada: {folder_path}"); return
    if output_format == "update_exif":
        excel_file_raw = input("\nIntroduce la ruta completa al archivo Excel generado previamente: ")
        excel_file_path = excel_file_raw.strip('"\' ')
        update_exif_from_excel(excel_file_path, folder_path); return
    print(f"\nProcesando imágenes en: {folder_path}")
    print(f"Formato de salida solicitado: {output_format.upper()}")
    photo_data_list: List[config.PhotoInfo] = []
    file_count, processed, coords_ok, coords_nok, errors_read, utm_err, date_ok, date_nok, desc_found, custom_name_found = 0,0,0,0,0,0,0,0,0,0
    try:
        img_ext = (".jpg", ".jpeg", ".tif", ".tiff", ".png")
        entries = [entry for entry in os.scandir(folder_path) if entry.is_file() and entry.name.lower().endswith(img_ext)]
        entries.sort(key=lambda x: x.name)
        file_count = len(entries)
        if file_count == 0: print("\nNo se encontraron archivos de imagen compatibles en la carpeta."); return
        print(f"Encontrados {file_count} archivos de imagen. Analizando EXIF...")
        for idx, entry in enumerate(entries):
            filename = entry.name; filepath = entry.path
            print(f"\rProcesando {idx + 1}/{file_count}: {filename:<50}", end='', flush=True)
            exif_result = get_exif_data(filepath); processed += 1
            if exif_result is None: errors_read += 1; coords_nok += 1; date_nok += 1; continue
            exif_data, orientation = exif_result
            if not exif_data: coords_nok += 1; date_nok += 1; continue
            photo_date = exif_data.get('DateTimeOriginal'); description = exif_data.get('ImageDescription')
            custom_name_from_exif = exif_data.get(config.PHOTO_INFO_CUSTOM_NAME_KEY)
            base_name, _ = os.path.splitext(filename); nome_archivo = base_name
            if photo_date: date_ok += 1
            else: date_nok += 1
            if description: desc_found += 1
            if custom_name_from_exif: custom_name_found +=1
            coordinates = get_coordinates(exif_data)
            if coordinates:
                latitude, longitude = coordinates
                utm_coords = convert_to_utm(latitude, longitude)
                if utm_coords and all(val is not None for val in utm_coords):
                    easting, northing, zone, hemisphere = utm_coords # type: ignore
                    photo_info: config.PhotoInfo = {'filename': filename, 'nome': nome_archivo, config.PHOTO_INFO_CUSTOM_NAME_KEY: custom_name_from_exif,
                                     'photo_date': photo_date, 'description': description, 'latitude': latitude, 'longitude': longitude,
                                     'utm_easting': easting, 'utm_northing': northing, 'utm_zone': zone, 'utm_hemisphere': hemisphere,
                                     'filepath': filepath, 'orientation': orientation}
                    photo_data_list.append(photo_info); coords_ok += 1
                else: print(f"\n   Warning: Falha ao converter UTM para {filename} (Lat/Lon: {latitude:.5f}, {longitude:.5f})"); utm_err += 1; coords_nok += 1
            else: coords_nok += 1
        print() 
    except OSError as e: print(f"\nError de Sistema listando archivos en '{folder_path}': {e}"); return
    except Exception as e_scan: # pylint: disable=broad-except
        print(f"\nError inesperado durante el escaneo de archivos: {e_scan}");
        if config.DEBUG_MODE: traceback.print_exc()
        return
    
    if config.DEBUG_MODE:
        print(f"DEBUG [process_folder]: ANÁLISIS COMPLETADO. Tamaño de photo_data_list: {len(photo_data_list)}")
        if not photo_data_list and file_count > 0:
            print("DEBUG [process_folder]: photo_data_list está VACÍA pero se encontraron archivos. Verificar lógica de get_coordinates/convert_to_utm o filtros.")
        elif photo_data_list:
            print("DEBUG [process_folder]: Primeros elementos de photo_data_list (si existen):")
            for i, item_debug in enumerate(photo_data_list[:2]):
                print(f"  Item {i}: {item_debug.get('filename')}, Coords OK: {'latitude' in item_debug}, CustomName: '{item_debug.get(config.PHOTO_INFO_CUSTOM_NAME_KEY)}'")
    
    print("\n--- Resumen del Análisis EXIF ---")
    print(f"  - Archivos de imagen encontrados: {file_count}\n  - Archivos procesados: {processed}")
    print(f"  - Errores de lectura de archivo/imagen: {errors_read}\n  - Fotos con coordenadas Lat/Lon válidas: {coords_ok}")
    print(f"  - Fotos sin coordenadas válidas: {coords_nok}")
    if utm_err > 0: print(f"      - Fallos conversión UTM (de coords válidas): {utm_err}")
    print(f"  - Fotos con fecha válida: {date_ok}\n  - Fotos sin fecha válida: {date_nok}")
    print(f"  - Fotos con descripción EXIF encontrada: {desc_found}")
    print(f"  - Fotos con Nome Personalizado (Tag {config.NOME_PERSONALIZADO_TAG_ID}) encontrado: {custom_name_found}")
    print("---------------------------------")

    if not photo_data_list:
        print("\nNo se encontraron fotos con coordenadas válidas suficientes para generar la salida.")
        if output_format != "update_exif": return
    else:
        if config.DEBUG_MODE: print(f"DEBUG [process_folder]: Entrando al bloque 'else' para generar archivos. Output format: {output_format}")
        print(f"\nSe encontraron {len(photo_data_list)} fotos con datos válidos.")
        print("Ordenando fotos por fecha (si disponible) y luego por nombre...")
        photo_data_list.sort(key=lambda item: (item.get("photo_date") or "9999", item["filename"]))
        folder_base_name = os.path.basename(os.path.normpath(folder_path))
        output_base_name = sanitize_filename(f"coordenadas_utm_{folder_base_name}_ordenado")
        output_generated = False; temp_files_to_clean: List[str] = []
        try:
            if config.DEBUG_MODE: print(f"DEBUG [process_folder]: Dentro del try para llamar a generadores. output_format='{output_format}'")
            if output_format == "excel":
                if config.DEBUG_MODE: print("DEBUG [process_folder]: Llamando a _generate_excel...")
                output_generated, temps = _generate_excel(photo_data_list, output_base_name)
                temp_files_to_clean.extend(temps)
            elif output_format == "kmz": 
                if config.DEBUG_MODE: print("DEBUG [process_folder]: Llamando a _generate_kmz...")
                output_generated, temps = _generate_kmz(photo_data_list, folder_base_name, output_base_name); temp_files_to_clean.extend(temps)
            elif output_format == "csv": 
                if config.DEBUG_MODE: print("DEBUG [process_folder]: Llamando a _generate_csv...")
                output_generated = _generate_csv(photo_data_list, output_base_name)
            elif output_format == "kml_simple": 
                if config.DEBUG_MODE: print("DEBUG [process_folder]: Llamando a _generate_kml_simple...")
                output_generated = _generate_kml_simple(photo_data_list, folder_base_name, output_base_name)
            if not output_generated and output_format != "update_exif": print(f"\nLa generación del archivo {output_format.upper()} falló debido a errores previos.")
        except Exception as e_generate: print(f"\nERROR CRÍTICO durante la generación del archivo {output_format.upper()}: {e_generate}"); traceback.print_exc() # pylint: disable=broad-except
        finally:
            if temp_files_to_clean:
                print(f"\nLimpiando {len(temp_files_to_clean)} archivos temporales...")
                cleaned_count = 0
                for temp_path in temp_files_to_clean:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                            cleaned_count += 1
                            if config.DEBUG_MODE: print(f"  -> Eliminado: {os.path.basename(temp_path)}")
                        except OSError as e_remove: print(f"  Warning: No se pudo eliminar archivo temporal '{temp_path}': {e_remove}")
                        except Exception as e_fatal: print(f"  ERROR fatal eliminando temporal '{temp_path}': {e_fatal}") # pylint: disable=broad-except
                    elif config.DEBUG_MODE: print(f"  -> No encontrado para eliminar: {os.path.basename(temp_path)}")
                if config.DEBUG_MODE: print(f"DEBUG: Limpieza finalizada. {cleaned_count} eliminados.")
    
    if file_count > 0 and processed == file_count and not photo_data_list and output_format != "update_exif":
        print("\nAnálisis completado. Todas las imágenes fueron procesadas pero ninguna contenía datos suficientes (ej. coordenadas) para la salida solicitada.")
    elif file_count > 0 and processed < file_count:
        print(f"\nProcesamiento parcial. Se procesaron {processed} de {file_count} imágenes. Verifique errores de lectura.")

    if config.DEBUG_MODE: print(f"DEBUG: [process_folder] === Fin process_folder ({output_format}) ===")

if __name__ == "__main__":
    if config.DEBUG_MODE: print("DEBUG: Iniciando __main__")
    print("\n--- Extractor/Actualizador Coordenadas y Descripciones EXIF v2.2 ---")
    print("---                 (Lat/Lon & UTM)                      ---")
    print(f"--- Modo Depuración: {'ACTIVO' if config.DEBUG_MODE else 'INACTIVO'} ---")
    if piexif is None:
        print("\n*** ADVERTENCIA: La librería 'piexif' no está disponible. ***")
        print("***             La opción 4 (Actualizar EXIF) no funcionará. ***")
        print("***             Instálala con: pip install piexif          ***")
    selected_folder = ""
    while True:
        folder_raw = input("\nIntroduce la ruta completa a la carpeta con las fotos: ")
        cleaned_folder = folder_raw.strip('"\' ')
        if config.DEBUG_MODE: print(f"DEBUG: Carpeta ingresada (limpia): '{cleaned_folder}'")
        if os.path.isdir(cleaned_folder):
            selected_folder = cleaned_folder
            if config.DEBUG_MODE: print("DEBUG: La ruta es un directorio válido.")
            break
        else: print(f"\nError: La ruta '{cleaned_folder}' no es una carpeta válida o no existe.")
    print("\nSelecciona la operación a realizar:")
    print("  --- Generar Archivos ---")
    print("  1: KMZ (Google Earth, fotos embebidas) [Título: NomePersonalizado > Descripcion > Archivo]")
    print("  2: CSV (Tabla de datos)")
    print("  3: Excel (Tabla con fotos, editable para NomePersonalizado y Descripcion)")
    print("  --- Actualizar Fotos ---")
    print("  4: Actualizar EXIF desde Excel (Descripcion y NomePersonalizado [Artist])")
    print("  --- Otros Formatos ---")
    print("  5: KML Simple (My Maps, puntos y datos, SIN fotos) [Título: NomePersonalizado > Descripcion > Archivo]")
    valid_options = {1: "kmz", 2: "csv", 3: "excel", 4: "update_exif", 5: "kml_simple"}
    selected_format = ""
    while True:
        try:
            choice_raw = input("Ingresa el número de la opción deseada: ")
            choice_num = int(choice_raw.strip())
            if choice_num in valid_options:
                chosen_format = valid_options[choice_num]
                if chosen_format == "update_exif" and piexif is None:
                    print("\nError: La librería 'piexif' es necesaria para esta opción y no está instalada.")
                    print("       Por favor, instálala ('pip install piexif') y reinicia el script.")
                else:
                    selected_format = chosen_format
                    if config.DEBUG_MODE: print(f"DEBUG: Opción numérica: {choice_num} -> Formato/Acción: '{selected_format}'")
                    break
            else: print("Número de opción inválido. Inténtalo de nuevo.")
        except ValueError: print("Entrada inválida. Por favor, ingresa solo el número de la opción.")
        except Exception as e: print(f"Error inesperado al leer la opción: {e}") # pylint: disable=broad-except
    if selected_folder and selected_format:
        if config.DEBUG_MODE: print(f"\nDEBUG: Llamando process_folder(folder='{selected_folder}', output_format='{selected_format}')...")
        process_folder(selected_folder, selected_format)
    else: print("\nError: No se pudo determinar la carpeta o el formato de salida.")
    print("\n--- Script Finalizado ---")
    if config.DEBUG_MODE: print("DEBUG: Fin __main__")
    # input("\nPresiona Enter para salir...")