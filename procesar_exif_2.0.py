# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Script para extraer coordenadas (Lat/Lon, UTM) y fecha de fotos EXIF.
# Genera archivos KMZ, CSV, Excel o KML simple. Optimiza tamaño para Excel.
# v2.0: Refatorado para PEP 8 (semicolons, line length, single-line blocks)
#       e limpeza de código. Funcionalidade da v1.8 mantida.
# -----------------------------------------------------------------------------

import os
# import sys  # Eliminado: No usado
from PIL import Image, ImageFile, UnidentifiedImageError # PIL_ExifTags ya no se importa aquí
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
# Las siguientes importaciones de typing son para los type hints directos en funciones
from typing import Optional, Dict, Any, Tuple, List, Union

# Importamos nuestro nuevo módulo de configuración
import config

# Esta configuración de PIL puede quedarse aquí o moverse a config.py.
# Por ahora la dejamos aquí ya que es una configuración directa del comportamiento de una librería.
ImageFile.LOAD_TRUNCATED_IMAGES = True

# --- Dependência para Opção 4 ---
try:
    import piexif
except ImportError:
    print("ERROR: La librería 'piexif' es necesaria para la opción 4 "
          "(Actualizar EXIF).")
    print("Por favor, instálala ejecutando: pip install piexif")
    piexif = None # type: ignore

# Ya no hay constantes ni type aliases definidos aquí, vienen de config.py

# --- Funções Auxiliares ---

def _decode_exif_string(value: bytes) -> str:
    """Tenta decodificar um valor EXIF bytes para string."""
    try:
        return value.decode('utf-8', 'strict').strip()
    except UnicodeDecodeError:
        try:
            return value.decode('latin-1', 'replace').strip()
        except Exception:
            return repr(value)


def get_exif_data(image_path: str) -> Optional[Tuple[config.ExifData, Optional[int]]]:
    """
    Extrai dados EXIF de uma imagem, incluindo orientação e descrição.

    Retorna:
        Uma tupla (exif_data_decoded, orientation) ou (None, None) em caso de erro
        na leitura do arquivo, ou ({}, None) se o arquivo for lido mas não
        tiver EXIF ou houver erro ao ler o EXIF.
    """
    if config.DEBUG_MODE:
        print(f"\nDEBUG: [get_exif_data] Procesando: {os.path.basename(image_path)}")

    if not os.path.exists(image_path):
        print(f"\nError: Archivo no encontrado: {image_path}")
        return None, None

    exif_data_raw = None
    orientation: Optional[int] = None
    gps_info_raw = None
    exif_data_decoded: config.ExifData = {}

    try:
        with Image.open(image_path) as image:
            if config.DEBUG_MODE:
                print(f"DEBUG: [get_exif_data] Imagen "
                      f"'{os.path.basename(image_path)}' abierta.")
            try:
                exif_data_raw = image.getexif()
                if not exif_data_raw:
                    if config.DEBUG_MODE:
                        print(f"DEBUG: [get_exif_data] No hay datos EXIF en "
                              f"'{os.path.basename(image_path)}'.")
                    return {}, None
            except Exception as e_exif:
                if isinstance(e_exif, (AttributeError, TypeError)) and \
                   'PngImageFile' in str(type(image)):
                    if config.DEBUG_MODE:
                        print("DEBUG: [get_exif_data] No hay datos EXIF (PNG).")
                    return {}, None
                print(f"\nWarning: No se pudo acceder a los datos EXIF para "
                      f"{os.path.basename(image_path)}: {e_exif}")
                return {}, None

            if exif_data_raw:
                if config.DEBUG_MODE:
                    print(f"DEBUG: [get_exif_data] Datos EXIF crudos obtenidos "
                          f"para '{os.path.basename(image_path)}'.")

                orientation = exif_data_raw.get(config.ORIENTATION_TAG_ID)

                try:
                    # GPS_IFD_TAG_ID puede ser None si el tag no existe en config.TAGS
                    if config.GPS_IFD_TAG_ID is not None:
                        gps_info_raw = exif_data_raw.get_ifd(config.GPS_IFD_TAG_ID)
                    else:
                        if config.DEBUG_MODE:
                            print("DEBUG: [get_exif_data] GPS_IFD_TAG_ID no está definido en config.TAGS.")
                        gps_info_raw = None
                except KeyError:
                    if config.DEBUG_MODE:
                        print("DEBUG: [get_exif_data] Tag GPSInfo (IFD) "
                              "no encontrada.")
                    gps_info_raw = None
                except Exception as e_gps:
                    print(f"\nWarning: Error accediendo a IFD GPS para "
                          f"{os.path.basename(image_path)}: {e_gps}")
                    gps_info_raw = None

                raw_date = exif_data_raw.get(config.DATETIME_ORIGINAL_TAG_ID) or \
                           exif_data_raw.get(config.DATETIME_TAG_ID)
                date_str = None
                if raw_date and isinstance(raw_date, str):
                    clean_date = raw_date.replace('\x00', '').strip()
                    try:
                        datetime.strptime(clean_date, '%Y:%m:%d %H:%M:%S')
                        date_str = clean_date
                    except ValueError:
                        print(f"\nWarning: Formato de fecha inválido "
                              f"'{clean_date}' en {os.path.basename(image_path)}")
                exif_data_decoded['DateTimeOriginal'] = date_str

                raw_desc = exif_data_raw.get(config.IMAGE_DESCRIPTION_TAG_ID)
                description = None
                if isinstance(raw_desc, str):
                    description = raw_desc.strip()
                elif isinstance(raw_desc, bytes):
                    description = _decode_exif_string(raw_desc)
                exif_data_decoded['ImageDescription'] = description

                skip_tags_values = []
                if config.GPS_IFD_TAG_ID is not None: skip_tags_values.append(config.GPS_IFD_TAG_ID)
                if config.ORIENTATION_TAG_ID is not None: skip_tags_values.append(config.ORIENTATION_TAG_ID)
                if config.IMAGE_DESCRIPTION_TAG_ID is not None: skip_tags_values.append(config.IMAGE_DESCRIPTION_TAG_ID)
                if config.DATETIME_ORIGINAL_TAG_ID is not None: skip_tags_values.append(config.DATETIME_ORIGINAL_TAG_ID)
                if config.DATETIME_TAG_ID is not None: skip_tags_values.append(config.DATETIME_TAG_ID)
                skip_tags = set(skip_tags_values)

                for tag_id, value in exif_data_raw.items():
                    if tag_id in skip_tags or tag_id is None:
                        continue
                    tag_name = config.TAGS.get(tag_id, f"Unknown_{tag_id}")
                    if isinstance(value, bytes):
                        decoded_value = _decode_exif_string(value)
                        if len(decoded_value) > 100 and decoded_value.startswith("b'"):
                            exif_data_decoded[tag_name] = (
                                f"<Binary data length {len(value)}>"
                            )
                        else:
                            exif_data_decoded[tag_name] = decoded_value
                    elif isinstance(value, str):
                        exif_data_decoded[tag_name] = value.strip()
                    else:
                        exif_data_decoded[tag_name] = value

                if gps_info_raw:
                    gps_data: Dict[str, Any] = {}
                    for gps_id, gps_val in gps_info_raw.items():
                        if gps_id is None:
                            continue
                        gps_name = config.GPSTAGS.get(gps_id, f"UnknownGPS_{gps_id}")

                        if isinstance(gps_val, bytes):
                            try:
                                decoded_gps = gps_val.decode('ascii', 'strict').strip()
                            except UnicodeDecodeError:
                                decoded_gps = _decode_exif_string(gps_val)
                            gps_data[gps_name] = decoded_gps
                        elif isinstance(gps_val, tuple) and gps_val:
                            try:
                                numeric_tuple = tuple(
                                    float(getattr(v, 'real', v)) for v in gps_val
                                )
                                if all(math.isfinite(n) for n in numeric_tuple):
                                    gps_data[gps_name] = numeric_tuple
                                else:
                                    if config.DEBUG_MODE:
                                        print("DEBUG: GPS tuple contem "
                                              f"não-finitos: {gps_val}")
                                    gps_data[gps_name] = repr(gps_val)
                            except (ValueError, TypeError):
                                if config.DEBUG_MODE:
                                    print("DEBUG: GPS tuple não numérico: "
                                          f"{gps_val}")
                                gps_data[gps_name] = repr(gps_val)
                        elif isinstance(gps_val, (int, float)):
                            if math.isfinite(gps_val):
                                gps_data[gps_name] = float(gps_val)
                            else:
                                gps_data[gps_name] = repr(gps_val)
                        else:
                            gps_data[gps_name] = gps_val

                    if gps_data:
                        exif_data_decoded["GPSInfo"] = gps_data

                return exif_data_decoded, orientation
            else:
                return {}, None

    except FileNotFoundError:
        print(f"\nError: Archivo no encontrado (dentro de get_exif): {image_path}")
        return None, None
    except UnidentifiedImageError:
        print(f"\nError: No se pudo identificar el archivo como imagen válida: "
              f"{os.path.basename(image_path)}")
        return None, None
    except OSError as e:
        print(f"\nError de Sistema/Archivo leyendo imagen "
              f"{os.path.basename(image_path)}: {e}")
        return None, None
    except Exception as e:
        print(f"\nError inesperado leyendo imagen "
              f"{os.path.basename(image_path)}: {e}")
        if config.DEBUG_MODE:
            traceback.print_exc()
        return None, None


def dms_to_decimal(degrees: config.Number, minutes: config.Number, seconds: config.Number,
                   direction: str) -> float:
    """
    Convierte Grados, Minutos, Segundos (DMS) a Grados Decimales.
    Lança ValueError em caso de erro de conversão ou direção inválida.
    """
    try:
        deg_f = float(getattr(degrees, 'real', degrees))
        min_f = float(getattr(minutes, 'real', minutes))
        sec_f = float(getattr(seconds, 'real', seconds))

        if not all(math.isfinite(x) for x in [deg_f, min_f, sec_f]):
            raise ValueError(f"Componente(s) DMS no finito: D={degrees}, "
                             f"M={minutes}, S={seconds}")

        if not (0 <= min_f < 60 and 0 <= sec_f < 60):
            print(f"\nWarning: Valores DMS fuera del range (Min={min_f}, "
                  f"Sec={sec_f}), continuando cálculo.")

        dd = deg_f + min_f / 60.0 + sec_f / 3600.0

        direction_upper = direction.upper()
        if direction_upper in ['S', 'W']:
            return -dd
        elif direction_upper in ['N', 'E']:
            return dd
        else:
            raise ValueError(f"Dirección GPS desconocida: '{direction}'")

    except (ValueError, TypeError, AttributeError) as e:
        raise ValueError(f"Error convirtiendo DMS ({degrees}, {minutes}, "
                         f"{seconds}, {direction}): {e}") from e


def get_coordinates(exif_data: config.ExifData) -> config.Coordinates:
    """
    Extrae Latitud y Longitud de los datos EXIF procesados.
    Retorna una tupla (latitude, longitude) o None si faltan datos,
    son inválidos o ocurre un error.
    """
    if not exif_data or "GPSInfo" not in exif_data:
        return None
    gps = exif_data["GPSInfo"]

    lat_dms = gps.get("GPSLatitude")
    lat_ref = gps.get("GPSLatitudeRef")
    lon_dms = gps.get("GPSLongitude")
    lon_ref = gps.get("GPSLongitudeRef")

    if not (lat_dms and lat_ref and lon_dms and lon_ref):
        if config.DEBUG_MODE:
            print("DEBUG: [get_coordinates] Faltan tags GPS esenciales.")
        return None
    if not isinstance(lat_ref, str) or not isinstance(lon_ref, str):
        if config.DEBUG_MODE:
            print(f"DEBUG: [get_coordinates] Refs GPS no son strings: "
                  f"LatRef={type(lat_ref)}, LonRef={type(lon_ref)}")
        return None
    if not isinstance(lat_dms, tuple) or len(lat_dms) != 3:
        if config.DEBUG_MODE:
            print(f"DEBUG: [get_coordinates] Lat DMS inválido: {lat_dms}")
        return None
    if not isinstance(lon_dms, tuple) or len(lon_dms) != 3:
        if config.DEBUG_MODE:
            print(f"DEBUG: [get_coordinates] Lon DMS inválido: {lon_dms}")
        return None

    try:
        _ = [float(getattr(v, 'real', v)) for v in lat_dms]
        _ = [float(getattr(v, 'real', v)) for v in lon_dms]
    except (ValueError, TypeError):
        if config.DEBUG_MODE:
            print(f"DEBUG: [get_coordinates] Conteúdo DMS não numérico: "
                  f"LAT={lat_dms}, LON={lon_dms}")
        return None

    try:
        latitude = dms_to_decimal(lat_dms[0], lat_dms[1], lat_dms[2], lat_ref)
        longitude = dms_to_decimal(lon_dms[0], lon_dms[1], lon_dms[2], lon_ref)

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            print(f"\nWarning: Coordenadas calculadas fuera de rango: "
                  f"Lat={latitude:.7f}, Lon={longitude:.7f}")
            return None

        return latitude, longitude

    except ValueError as e:
        print(f"\nError procesando coordenadas DMS: {e}")
        return None
    except Exception as e_gen:
        print(f"\nError inesperado en get_coordinates: {e_gen}")
        if config.DEBUG_MODE:
            traceback.print_exc()
        return None


def convert_to_utm(latitude: float, longitude: float) -> config.UTMCoordinates:
    """
    Convierte coordenadas Lat/Lon (WGS84) a UTM (Este, Norte, Zona, Hemisferio).
    Retorna (easting, northing, zone, hemisphere) ou (None, None, None, None).
    """
    if not isinstance(latitude, (int, float)) or \
       not isinstance(longitude, (int, float)):
        print(f"\nError UTM: Latitud/Longitud no numérica "
              f"({type(latitude)}, {type(longitude)})")
        return None, None, None, None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        print(f"\nError UTM: Coordenadas Lat/Lon fuera de rango "
              f"({latitude}, {longitude})")
        return None, None, None, None

    try:
        zone = math.floor((longitude + 180) / 6) + 1
        hemisphere = 'N' if latitude >= 0 else 'S'
        epsg_code_base = 32600 if latitude >= 0 else 32700
        epsg_code = epsg_code_base + zone

        crs_wgs84 = pyproj.CRS("EPSG:4326")
        crs_utm = pyproj.CRS(f"EPSG:{epsg_code}")
        transformer = pyproj.Transformer.from_crs(crs_wgs84, crs_utm,
                                                  always_xy=True)

        easting, northing = transformer.transform(longitude, latitude)

        if not math.isfinite(easting) or not math.isfinite(northing):
            raise ValueError("Resultado da transformação UTM não finito: "
                             f"E={easting}, N={northing}")

        return easting, northing, zone, hemisphere

    except pyproj.exceptions.CRSError as e_crs:
        print(f"\nError UTM: Problema com o sistema de coordenadas "
              f"(EPSG:{epsg_code}?): {e_crs}")
        return None, None, None, None
    except ValueError as e_val:
        print(f"\nError UTM: Problema nos valores durante a conversão: {e_val}")
        return None, None, None, None
    except Exception as e:
        print(f"\nError inesperado en la conversión UTM para "
              f"({latitude}, {longitude}): {e}")
        if config.DEBUG_MODE:
            traceback.print_exc()
        return None, None, None, None


def sanitize_filename(name: str) -> str:
    """Limpia un nombre de archivo eliminando caracteres inválidos y espacios."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.replace(' ', '_')
    return name[:100]


def apply_orientation(image: Image.Image, orientation: Optional[int]) -> Image.Image:
    """Aplica a orientação EXIF a uma cópia da imagem PIL."""
    actions = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }
    transpose_action = actions.get(orientation)

    if transpose_action:
        original_mode = image.mode
        try:
            if config.DEBUG_MODE:
                print(f"DEBUG: [apply_orientation] Aplicando orientação "
                      f"{orientation} ({transpose_action.name})") # type: ignore

            oriented_image = image.transpose(transpose_action)

            if oriented_image.mode != original_mode and \
               original_mode not in ('P', 'LA'):
                if config.DEBUG_MODE:
                    print("DEBUG: [apply_orientation] Modo mudou de "
                          f"{original_mode} para {oriented_image.mode}, "
                          "tentando reverter para RGB/RGBA")
                try:
                    if 'A' in oriented_image.mode:
                        oriented_image = oriented_image.convert('RGBA')
                    else:
                        oriented_image = oriented_image.convert('RGB')
                except Exception as e_conv:
                    print(f"\nWarning: Falha ao reconverter modo após "
                          f"orientação: {e_conv}")
                    return image

            return oriented_image
        except Exception as e:
            print(f"\nWarning: Falha ao aplicar orientação EXIF {orientation}: {e}")
            return image
    return image


def update_exif_from_excel(excel_path: str, image_folder_path: str) -> None:
    """
    Lee un archivo Excel (generado por este script) y actualiza el tag EXIF
    'ImageDescription' en las imágenes correspondientes en la carpeta.
    """
    if piexif is None:
        print("\nERROR: La librería 'piexif' no está instalada. "
              "No se puede ejecutar esta opción.")
        return

    print("\n--- Actualizando Descripciones EXIF desde Excel ---")
    print(f"Archivo Excel: {excel_path}")
    print(f"Carpeta de Imágenes: {image_folder_path}")
    print("\nIMPORTANTE: Esta operación modificará los archivos de imagen "
          "originales.")

    confirm_raw = input("¿Desea continuar? (S/n): ").strip()
    if confirm_raw.lower() == 'n':
        print("Operación cancelada.")
        return

    if not os.path.isfile(excel_path):
        print(f"\nError: Archivo Excel no encontrado: {excel_path}")
        return
    if not os.path.isdir(image_folder_path):
        print(f"\nError: Carpeta de imágenes no encontrada: {image_folder_path}")
        return

    updated_count = 0
    skipped_no_desc = 0
    skipped_no_file = 0
    error_read_excel = 0
    error_exif_update = 0
    total_rows = 0

    try:
        df = None
        print(f"\nLeyendo archivo Excel '{os.path.basename(excel_path)}'...")
        try:
            df = pd.read_excel(excel_path, sheet_name='Coordenadas_UTM_Data')
            print("  -> Hoja 'Coordenadas_UTM_Data' leída.")
        except ValueError:
            try:
                print("  -> Hoja 'Coordenadas_UTM_Data' no encontrada, "
                      "intentando leer la primera hoja...")
                df = pd.read_excel(excel_path, sheet_name=0)
                print("  -> Primera hoja leída.")
            except Exception as read_generic_err:
                print("\nError: No se pudo leer ninguna hoja válida del "
                      f"archivo Excel: {read_generic_err}")
                error_read_excel += 1
                return
        except Exception as read_sheet_err:
            print("\nError al leer la hoja 'Coordenadas_UTM_Data': "
                  f"{read_sheet_err}")
            error_read_excel += 1
            return

        if df is None:
            print("\nError: No se cargaron datos del Excel.")
            return

        required_cols = ['filename', 'Descripcion']
        if not all(col in df.columns for col in required_cols):
            print("\nError: El archivo Excel debe contener al menos las "
                  f"columnas: {', '.join(required_cols)}.")
            print(f"       Columnas encontradas: {list(df.columns)}")
            return

        total_rows = len(df)
        print(f"Procesando {total_rows} filas del Excel para actualizar EXIF...")

        for index, row in df.iterrows():
            current_row_num = index + 2
            filename_raw = row.get('filename')
            description_raw = row.get('Descripcion')

            if pd.isna(filename_raw) or \
               not isinstance(filename_raw, str) or \
               not filename_raw.strip():
                if config.DEBUG_MODE:
                    print(f"DEBUG: Fila {current_row_num} omitida "
                          "(filename inválido o ausente)")
                continue

            filename = filename_raw.strip()
            image_path = os.path.join(image_folder_path, filename)

            description_str = ""
            if not pd.isna(description_raw):
                if isinstance(description_raw, (int, float)):
                    description_str = str(description_raw).strip()
                elif isinstance(description_raw, str):
                    description_str = description_raw.strip()

            if not description_str:
                if config.DEBUG_MODE:
                    print(f"DEBUG: Fila {current_row_num} ('{filename}') "
                          "omitida (sin descripción válida).")
                skipped_no_desc += 1
                continue

            if not os.path.isfile(image_path):
                print(f"\nWarning: Imagen no encontrada para fila "
                      f"{current_row_num} ('{filename}'), omitiendo "
                      "actualización.")
                skipped_no_file += 1
                continue

            print(f"\rActualizando {index + 1}/{total_rows}: {filename}...",
                  end='', flush=True)
            try:
                exif_dict = piexif.load(image_path)

                if '0th' not in exif_dict:
                    exif_dict['0th'] = {}

                if config.DEBUG_MODE and \
                   piexif.ImageIFD.ImageDescription not in exif_dict.get('0th', {}): # type: ignore
                    print(" [Tag ImageDescription ausente, será adicionado]", end='')

                exif_dict['0th'][piexif.ImageIFD.ImageDescription] = \
                    description_str.encode('utf-8') # type: ignore

                exif_bytes = piexif.dump(exif_dict)
                piexif.insert(exif_bytes, image_path)
                updated_count += 1

            except FileNotFoundError:
                print(f"\nError interno (FileNotFound): Archivo '{filename}' "
                      "no encontrado durante actualización EXIF.")
                error_exif_update += 1
            except piexif.InvalidImageDataError: # type: ignore
                print(f"\nError EXIF: Datos de imagen inválidos o EXIF "
                      f"corrupto en '{filename}'. No se pudo actualizar.")
                error_exif_update += 1
            except ValueError as ve:
                print(f"\nError EXIF: Problema con datos EXIF existentes en "
                      f"'{filename}': {ve}. No se pudo actualizar.")
                error_exif_update += 1
            except OSError as oe:
                print(f"\nError de Sistema al escribir EXIF en '{filename}': {oe}")
                error_exif_update += 1
            except Exception as e:
                print(f"\nError inesperado actualizando EXIF para '{filename}': {e}")
                if config.DEBUG_MODE:
                    traceback.print_exc()
                error_exif_update += 1
        print()

        print("\n--- Resumen Actualización EXIF ---")
        print(f"  - Filas leídas del Excel: {total_rows}")
        print(f"  - Imágenes actualizadas con descripción: {updated_count}")
        print(f"  - Omitidas (sin descripción válida en Excel): {skipped_no_desc}")
        print(f"  - Omitidas (archivo de imagen no encontrado): {skipped_no_file}")
        print(f"  - Errores leyendo Excel: {error_read_excel}")
        print(f"  - Errores durante la actualización EXIF: {error_exif_update}")
        print("----------------------------------")

    except Exception as e:
        print(f"\nError fatal durante el proceso de actualización desde Excel: {e}")
        if config.DEBUG_MODE:
            traceback.print_exc()

# --- Funções para Geração de Saída ---

def _generate_kmz(photo_data_list: List[config.PhotoInfo], folder_name: str,
                  out_base: str) -> Tuple[bool, List[str]]:
    """Gera o arquivo KMZ com pontos, descrições e imagens embutidas."""
    kml = simplekml.Kml(name=f"Coords {folder_name}")
    print("\nGenerando KMZ (Google Earth)...")
    total = len(photo_data_list)
    temps_to_delete: List[str] = []
    generated = False
    skipped_coords = 0

    for idx, data in enumerate(photo_data_list):
        filename = data['filename']
        print(f"\r  -> Procesando KMZ {idx + 1}/{total}: {filename[:40]}...",
              end="", flush=True)

        lat = data.get('latitude')
        lon = data.get('longitude')
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
            print(f"\n   Skipping {filename}: Coordenadas inválidas ({lat}, {lon})")
            skipped_coords += 1
            continue

        description = data.get('description')
        nome = data.get('nome')
        point_name = description or nome or filename

        pnt = kml.newpoint(name=point_name, coords=[(lon, lat)]) # type: ignore

        if data.get("photo_date"):
            try:
                dt = datetime.strptime(data['photo_date'], '%Y:%m:%d %H:%M:%S')
                pnt.timestamp.when = dt.strftime('%Y-%m-%dT%H:%M:%SZ') # type: ignore
            except (ValueError, TypeError):
                pass

        desc_html_parts = []
        if nome:
            desc_html_parts.append(f"<b>Nome:</b> {nome}")
        if description:
            desc_html_parts.append(f"<b>Descripción:</b> {description}")
        desc_html_parts.append(f"<b>Archivo:</b> {filename}")
        desc_html_parts.append(f"<b>Data:</b> {data.get('photo_date', 'N/A')}")

        utm_e_val = data.get('utm_easting')
        utm_n_val = data.get('utm_northing')
        utm_e = f"{utm_e_val:.2f}" if isinstance(utm_e_val, (int, float)) else 'N/A'
        utm_n = f"{utm_n_val:.2f}" if isinstance(utm_n_val, (int, float)) else 'N/A'
        utm_z = data.get('utm_zone', 'N/A')
        utm_h = data.get('utm_hemisphere', '')
        desc_html_parts.append(f"<b>UTM:</b> Zona {utm_z}{utm_h}, E: {utm_e}, N: {utm_n}")

        img_path = data.get('filepath')
        orientation = data.get('orientation')
        temp_img_path = None
        img_ref_in_kml = None
        img_copy_kmz = None

        if img_path and os.path.exists(img_path):
            try:
                with Image.open(img_path) as img_orig:
                    img_oriented = apply_orientation(img_orig, orientation)
                    img_copy_kmz = img_oriented.copy()

                    img_copy_kmz.thumbnail(
                        (config.KMZ_IMAGE_WIDTH, config.KMZ_IMAGE_WIDTH * 10),
                        Image.Resampling.LANCZOS
                    )

                    img_format_out = 'JPEG'
                    save_options = {'quality': config.KMZ_IMAGE_QUALITY, 'optimize': True}

                    if img_copy_kmz.mode in ('P', 'RGBA', 'LA'):
                        if config.DEBUG_MODE:
                            print(f" [Convertendo modo {img_copy_kmz.mode} "
                                  "para RGB]", end="")
                        try:
                            background = Image.new("RGB", img_copy_kmz.size,
                                                   (255, 255, 255))
                            mask = None
                            if 'A' in img_copy_kmz.mode:
                                mask = img_copy_kmz.split()[-1]

                            img_to_paste = img_copy_kmz.convert("RGBA").convert("RGB")
                            background.paste(img_to_paste, (0, 0), mask=mask)
                            img_copy_kmz.close()
                            img_copy_kmz = background
                        except Exception as e_conv_kmz:
                            print(f"\n   Warning: Falha ao converter imagem "
                                  f"{filename} para KMZ: {e_conv_kmz}")
                            img_copy_kmz.close()
                            img_copy_kmz = None

                    if img_copy_kmz:
                        suffix = '.jpg'
                        with tempfile.NamedTemporaryFile(delete=False,
                                                         suffix=suffix,
                                                         prefix="kmz_") as tf:
                            temp_img_path = tf.name
                            img_copy_kmz.save(tf, format=img_format_out, **save_options)

                if temp_img_path and os.path.exists(temp_img_path):
                    temps_to_delete.append(temp_img_path)
                    img_ref_in_kml = kml.addfile(temp_img_path) # type: ignore

            except UnidentifiedImageError:
                print(f"\n   Warning: No se pudo identificar {filename} "
                      "como imagen para KMZ.")
            except Exception as e_img:
                print(f"\n   Warning: Error procesando imagen {filename} "
                      f"para KMZ: {e_img}")
            finally:
                if img_copy_kmz:
                    try:
                        img_copy_kmz.close()
                    except Exception:
                        pass

        desc_html = "<br/>".join(desc_html_parts)
        if img_ref_in_kml:
            desc_html += (
                f'<hr/><img src="{img_ref_in_kml}" alt="Foto" '
                f'width="{config.KMZ_IMAGE_WIDTH}" />'
            )
        else:
            desc_html += '<hr/><i>Imagen no disponible o no embebida.</i>'
        pnt.description = desc_html # type: ignore
    print()

    if skipped_coords > 0:
        print(f"Aviso: {skipped_coords} puntos omitidos por coordenadas inválidas.")

    kmz_file = f"{out_base}.kmz"
    try:
        kml.savekmz(kmz_file) # type: ignore
        print(f"\nArchivo KMZ guardado con éxito: {os.path.abspath(kmz_file)}")
        generated = True
    except Exception as e_save:
        print(f"\nERROR FATAL guardando KMZ {kmz_file}: {e_save}")
        traceback.print_exc()

    return generated, temps_to_delete


def _generate_csv(photo_data_list: List[config.PhotoInfo], out_base: str) -> bool:
    """Gera o arquivo CSV com os dados extraídos."""
    print("\nGenerando CSV...")
    generated = False
    try:
        df = pd.DataFrame(photo_data_list)

        cols_to_include = [
            'nome', 'description', 'filename', 'photo_date',
            'latitude', 'longitude', 'utm_easting', 'utm_northing',
            'utm_zone', 'utm_hemisphere'
        ]
        cols_in_df = [col for col in cols_to_include if col in df.columns]
        df_csv = df[cols_in_df].copy()

        for col in ['latitude', 'longitude']:
            if col in df_csv:
                df_csv[col] = df_csv[col].apply(
                    lambda x: f"{x:.7f}" if isinstance(x, (int, float)) else x
                )
        for col in ['utm_easting', 'utm_northing']:
            if col in df_csv:
                df_csv[col] = df_csv[col].apply(
                    lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x
                )

        csv_file = f"{out_base}.csv"
        df_csv.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"\nArchivo CSV guardado con éxito: {os.path.abspath(csv_file)}")
        generated = True
    except Exception as e:
        print(f"\nERROR FATAL generando CSV: {e}")
        if config.DEBUG_MODE:
            traceback.print_exc()

    return generated


def _generate_excel(photo_data_list: List[config.PhotoInfo],
                    out_base: str) -> Tuple[bool, List[str]]:
    """Gera o arquivo Excel com dados e imagens redimensionadas."""
    print("\nGenerando Excel con imágenes (puede tardar)...")
    excel_file = f"{out_base}_con_fotos.xlsx"
    generated = False
    temps_to_delete: List[str] = []

    try:
        df = pd.DataFrame(photo_data_list)

        cols_data_order = [
            'Nome', 'Descripcion', 'filename', 'photo_date',
            'utm_easting', 'utm_northing', 'utm_zone', 'utm_hemisphere'
        ]
        df_out = pd.DataFrame()

        if 'nome' in df.columns:
            df_out['Nome'] = df['nome'].fillna("").astype(str)
        else:
            df_out['Nome'] = ""

        if 'description' in df.columns:
            df_out['Descripcion'] = df['description'].fillna("").astype(str)
        else:
            df_out['Descripcion'] = ""

        df_out['filename'] = df['filename']

        if 'photo_date' in df.columns:
             df_out['photo_date'] = df['photo_date']
        if 'utm_easting' in df.columns:
             df_out['utm_easting'] = df['utm_easting'].apply(
                 lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x
             )
        if 'utm_northing' in df.columns:
             df_out['utm_northing'] = df['utm_northing'].apply(
                 lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x
             )
        if 'utm_zone' in df.columns:
             df_out['utm_zone'] = df['utm_zone']
        if 'utm_hemisphere' in df.columns:
             df_out['utm_hemisphere'] = df['utm_hemisphere']

        final_cols_data = [col for col in cols_data_order if col in df_out.columns]
        df_out = df_out[final_cols_data]

        with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
            df_out.to_excel(writer, sheet_name='Coordenadas_UTM_Data',
                            startcol=config.EXCEL_DATA_START_COL, index=False)
            workbook = writer.book
            worksheet = writer.sheets['Coordenadas_UTM_Data']

            worksheet.set_column(config.EXCEL_IMAGE_COL, config.EXCEL_IMAGE_COL,
                                 config.EXCEL_TARGET_IMAGE_WIDTH_PX * config.EXCEL_COL_WIDTH_FACTOR)
            worksheet.set_column(config.EXCEL_NAME_COL, config.EXCEL_NAME_COL, 25)
            worksheet.set_column(config.EXCEL_DESC_COL, config.EXCEL_DESC_COL, 40)

            total = len(df)
            print("  -> Insertando imágenes en Excel...")
            for idx, row_data in df.iterrows():
                filename = row_data.get('filename', 'N/A')
                filepath = row_data.get('filepath')
                orientation = row_data.get('orientation')
                excel_row_index = idx + 1

                print(f"\r     {idx + 1}/{total}: {filename[:40]}...",
                      end='', flush=True)

                if not filepath or not os.path.exists(filepath):
                    print(f"\n     Skipping image for row {excel_row_index}: "
                          f"File not found '{filepath}'")
                    worksheet.set_row(excel_row_index, 15)
                    continue

                temp_img_path_excel = None
                processed_image = None

                try:
                    with Image.open(filepath) as img_orig:
                        img_oriented = apply_orientation(img_orig, orientation)
                        processed_image = img_oriented.copy()

                    w_orig, h_orig = processed_image.size
                    if w_orig == 0 or h_orig == 0:
                        raise ValueError("Dimensões inválidas da imagem.")

                    thumb_w = int(config.EXCEL_TARGET_IMAGE_WIDTH_PX *
                                  config.EXCEL_TEMP_IMAGE_SCALE_FACTOR)
                    # thumb_h = int(h_orig * (thumb_w / w_orig)) # No se usa, se recalcula abajo
                    processed_image.thumbnail((thumb_w, h_orig * (thumb_w / w_orig) * 2), # Aumentar altura para evitar recorte
                                              Image.Resampling.LANCZOS)
                    final_w, final_h = processed_image.size

                    scale_factor = config.EXCEL_TARGET_IMAGE_WIDTH_PX / final_w
                    row_height = (final_h * scale_factor) * config.EXCEL_ROW_HEIGHT_FACTOR + 5
                    worksheet.set_row(excel_row_index, row_height)

                    save_format = 'JPEG'
                    save_suffix = '.jpg'
                    save_options_excel: Dict[str, Any] = {'quality': config.EXCEL_TEMP_IMAGE_QUALITY}


                    if processed_image.mode in ('P', 'LA', 'RGBA'):
                        save_format = 'PNG'
                        save_suffix = '.png'
                        save_options_excel = {'optimize': True}
                        if processed_image.mode in ('P', 'LA'):
                            try:
                                if config.DEBUG_MODE:
                                    print(f" [Convertendo {processed_image.mode} "
                                          "para RGBA]", end="")
                                processed_image = processed_image.convert("RGBA")
                            except Exception as conv_e:
                                print(f"\n     Warning: Falha ao converter "
                                      f"{processed_image.mode}->RGBA para "
                                      f"{filename}: {conv_e}")
                    elif processed_image.mode == 'CMYK':
                        try:
                            if config.DEBUG_MODE:
                                print(" [Convertendo CMYK para RGB]", end="")
                            processed_image = processed_image.convert("RGB")
                            save_format = 'JPEG'
                            save_suffix = '.jpg'
                            save_options_excel = {'quality': config.EXCEL_TEMP_IMAGE_QUALITY}
                        except Exception as conv_e:
                            print("\n     Warning: Falha ao converter CMYK->RGB "
                                  f"para {filename}: {conv_e}")
                            raise ValueError("Não foi possível converter CMYK "
                                             f"para {filename}")

                    with tempfile.NamedTemporaryFile(delete=False,
                                                     suffix=save_suffix,
                                                     prefix="excel_") as tf:
                        temp_img_path_excel = tf.name
                        processed_image.save(tf, format=save_format, **save_options_excel)

                    if temp_img_path_excel and os.path.exists(temp_img_path_excel):
                        temps_to_delete.append(temp_img_path_excel)
                        insert_options = {
                            'x_scale': scale_factor,
                            'y_scale': scale_factor,
                            'object_position': 1
                        }
                        worksheet.insert_image(excel_row_index, config.EXCEL_IMAGE_COL,
                                               temp_img_path_excel, insert_options)

                except UnidentifiedImageError:
                    print(f"\n     Warning: No se pudo identificar {filename} "
                          "como imagen para Excel.")
                    worksheet.set_row(excel_row_index, 15)
                except ValueError as ve:
                    print(f"\n     Warning: Error de valor procesando imagen "
                          f"{filename} para Excel: {ve}")
                    worksheet.set_row(excel_row_index, 15)
                except Exception as img_e:
                    print(f"\n     Error procesando imagen {filename} para Excel "
                          f"(fila {excel_row_index}): {img_e}")
                    worksheet.set_row(excel_row_index, 15)
                finally:
                    if processed_image:
                        try:
                            processed_image.close()
                        except Exception:
                            pass
            print()

        print(f"\nArchivo Excel guardado con éxito: {os.path.abspath(excel_file)}")
        generated = True

    except Exception as e:
        print(f"\nERROR FATAL generando archivo Excel: {e}")
        if config.DEBUG_MODE:
            traceback.print_exc()

    return generated, temps_to_delete


def _generate_kml_simple(photo_data_list: List[config.PhotoInfo], folder_name: str,
                         out_base: str) -> bool:
    """
    Gera o arquivo KML simples (sem imagens embutidas), compatível com My Maps.
    """
    kml = simplekml.Kml(name=f"Coords {folder_name} (Simple)") # type: ignore
    print("\nGenerando KML simple (My Maps)...")
    total = len(photo_data_list)
    generated = False
    skipped_coords = 0

    for idx, data in enumerate(photo_data_list):
        filename = data['filename']
        print(f"\r  -> Añadiendo KML simple {idx + 1}/{total}: {filename[:40]}...",
              end="", flush=True)

        lat = data.get('latitude')
        lon = data.get('longitude')
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
            print(f"\n   Skipping {filename}: Coordenadas inválidas ({lat}, {lon})")
            skipped_coords += 1
            continue

        description = data.get('description')
        nome = data.get('nome')
        point_name = description or nome or filename

        pnt = kml.newpoint(name=point_name, coords=[(lon, lat)]) # type: ignore

        if data.get("photo_date"):
            try:
                dt = datetime.strptime(data['photo_date'], '%Y:%m:%d %H:%M:%S')
                pnt.timestamp.when = dt.strftime('%Y-%m-%dT%H:%M:%SZ') # type: ignore
            except (ValueError, TypeError):
                pass

        desc_html_parts = []
        if nome:
            desc_html_parts.append(f"<b>Nome:</b> {nome}")
        if description:
            desc_html_parts.append(f"<b>Descripción:</b> {description}")
        desc_html_parts.append(f"<b>Archivo:</b> {filename}")
        desc_html_parts.append(f"<b>Data:</b> {data.get('photo_date', 'N/A')}")

        utm_e_val = data.get('utm_easting')
        utm_n_val = data.get('utm_northing')
        utm_e = f"{utm_e_val:.2f}" if isinstance(utm_e_val, (int, float)) else 'N/A'
        utm_n = f"{utm_n_val:.2f}" if isinstance(utm_n_val, (int, float)) else 'N/A'
        utm_z = data.get('utm_zone', 'N/A')
        utm_h = data.get('utm_hemisphere', '')
        desc_html_parts.append(f"<b>UTM:</b> Zona {utm_z}{utm_h}, E: {utm_e}, N: {utm_n}")

        pnt.description = "<br/>".join(desc_html_parts) # type: ignore
    print()

    if skipped_coords > 0:
        print(f"Aviso: {skipped_coords} puntos omitidos por coordenadas inválidas.")

    kml_file = f"{out_base}_simple.kml"
    try:
        kml.save(kml_file) # type: ignore
        print("\nArchivo KML simple guardado con éxito: "
              f"{os.path.abspath(kml_file)}")
        generated = True
    except Exception as e:
        print(f"\nERROR FATAL guardando KML simple {kml_file}: {e}")

    return generated


# --- Função Principal de Processamento ---
def process_folder(folder_path: str, output_format: str) -> None:
    """
    Processa uma pasta de imagens: extrai dados EXIF e gera o arquivo de saída
    ou atualiza EXIF com base no formato especificado.
    """
    if config.DEBUG_MODE:
        print(f"\nDEBUG: [process_folder] Iniciando para: '{folder_path}', "
              f"Formato: '{output_format.upper()}'")

    if not os.path.isdir(folder_path):
        print(f"Error: Carpeta no encontrada: {folder_path}")
        return

    if output_format == "update_exif":
        excel_file_raw = input("\nIntroduce la ruta completa al archivo Excel "
                               "generado previamente (con las descripciones): ")
        excel_file_path = excel_file_raw.strip('"\' ')
        update_exif_from_excel(excel_file_path, folder_path)
        return

    print(f"\nProcesando imágenes en: {folder_path}")
    print(f"Formato de salida solicitado: {output_format.upper()}")

    photo_data_list: List[config.PhotoInfo] = []
    file_count = 0
    processed = 0
    coords_ok = 0
    coords_nok = 0
    errors_read = 0
    utm_err = 0
    date_ok = 0
    date_nok = 0
    desc_found = 0

    try:
        img_ext = (".jpg", ".jpeg", ".tif", ".tiff", ".png")
        entries = [entry for entry in os.scandir(folder_path)
                   if entry.is_file() and entry.name.lower().endswith(img_ext)]
        entries.sort(key=lambda x: x.name)
        file_count = len(entries)

        if file_count == 0:
            print("\nNo se encontraron archivos de imagen compatibles "
                  f"({', '.join(img_ext)}) en la carpeta.")
            return

        print(f"Encontrados {file_count} archivos de imagen. Analizando EXIF...")

        for idx, entry in enumerate(entries):
            filename = entry.name
            filepath = entry.path
            print(f"\rProcesando {idx + 1}/{file_count}: {filename:<50}",
                  end='', flush=True)

            exif_result = get_exif_data(filepath)
            processed += 1

            if exif_result is None:
                errors_read += 1
                coords_nok += 1
                date_nok += 1
                continue

            exif_data, orientation = exif_result
            if not exif_data: # Si es {}
                coords_nok += 1
                date_nok += 1
                continue

            photo_date = exif_data.get('DateTimeOriginal')
            description = exif_data.get('ImageDescription')
            base_name, _ = os.path.splitext(filename)
            nome = base_name

            if photo_date:
                date_ok += 1
            else:
                date_nok += 1
            if description:
                desc_found += 1

            coordinates = get_coordinates(exif_data)

            if coordinates:
                latitude, longitude = coordinates
                utm_coords = convert_to_utm(latitude, longitude)

                if utm_coords and all(val is not None for val in utm_coords):
                    easting, northing, zone, hemisphere = utm_coords # type: ignore
                    photo_info: config.PhotoInfo = {
                        'filename': filename,
                        'nome': nome,
                        'photo_date': photo_date,
                        'description': description,
                        'latitude': latitude,
                        'longitude': longitude,
                        'utm_easting': easting,
                        'utm_northing': northing,
                        'utm_zone': zone,
                        'utm_hemisphere': hemisphere,
                        'filepath': filepath,
                        'orientation': orientation
                    }
                    photo_data_list.append(photo_info)
                    coords_ok += 1
                else:
                    print(f"\n   Warning: Falha ao converter UTM para {filename} "
                          f"(Lat/Lon: {latitude:.5f}, {longitude:.5f})")
                    utm_err += 1
                    coords_nok += 1
            else:
                coords_nok += 1
        print()

    except OSError as e:
        print(f"\nError de Sistema listando archivos en '{folder_path}': {e}")
        return
    except Exception as e_scan:
        print(f"\nError inesperado durante el escaneo de archivos: {e_scan}")
        if config.DEBUG_MODE:
            traceback.print_exc()
        return

    print("\n--- Resumen del Análisis EXIF ---")
    print(f"  - Archivos de imagen encontrados: {file_count}")
    print(f"  - Archivos procesados: {processed}")
    print(f"  - Errores de lectura de archivo/imagen: {errors_read}")
    print(f"  - Fotos con coordenadas Lat/Lon válidas: {coords_ok}")
    print(f"  - Fotos sin coordenadas válidas: {coords_nok}")
    if utm_err > 0:
        print(f"      - Fallos conversión UTM (de coords válidas): {utm_err}")
    print(f"  - Fotos con fecha válida: {date_ok}")
    print(f"  - Fotos sin fecha válida: {date_nok}")
    print(f"  - Fotos con descripción EXIF encontrada: {desc_found}")
    print("---------------------------------")

    if not photo_data_list:
        print("\nNo se encontraron fotos con coordenadas válidas suficientes "
              "para generar la salida.")
    else:
        print(f"\nSe encontraron {len(photo_data_list)} fotos con datos válidos.")
        print("Ordenando fotos por fecha (si disponible) y luego por nombre...")
        photo_data_list.sort(key=lambda item: (
            item.get("photo_date") or "9999", item["filename"]
        ))

        folder_base_name = os.path.basename(os.path.normpath(folder_path))
        output_base_name = sanitize_filename(
            f"coordenadas_utm_{folder_base_name}_ordenado"
        )

        output_generated = False
        temp_files_to_clean: List[str] = []

        try:
            if output_format == "kmz":
                output_generated, temps = _generate_kmz(
                    photo_data_list, folder_base_name, output_base_name
                )
                temp_files_to_clean.extend(temps)
            elif output_format == "csv":
                output_generated = _generate_csv(
                    photo_data_list, output_base_name
                )
            elif output_format == "excel":
                output_generated, temps = _generate_excel(
                    photo_data_list, output_base_name
                )
                temp_files_to_clean.extend(temps)
            elif output_format == "kml_simple":
                output_generated = _generate_kml_simple(
                    photo_data_list, folder_base_name, output_base_name
                )

            if not output_generated and output_format != "update_exif":
                print(f"\nLa generación del archivo {output_format.upper()} "
                      "falló debido a errores previos.")

        except Exception as e_generate:
            print(f"\nERROR CRÍTICO durante la generación del archivo "
                  f"{output_format.upper()}: {e_generate}")
            traceback.print_exc()
        finally:
            if temp_files_to_clean:
                print(f"\nLimpiando {len(temp_files_to_clean)} archivos temporales...")
                cleaned_count = 0
                for temp_path in temp_files_to_clean:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                            cleaned_count += 1
                            if config.DEBUG_MODE:
                                print("  -> Eliminado: "
                                      f"{os.path.basename(temp_path)}")
                        except OSError as e_remove:
                            print(f"  Warning: No se pudo eliminar archivo "
                                  f"temporal '{temp_path}': {e_remove}")
                        except Exception as e_fatal:
                            print(f"  ERROR fatal eliminando temporal "
                                  f"'{temp_path}': {e_fatal}")
                    elif config.DEBUG_MODE:
                        print("  -> No encontrado para eliminar: "
                              f"{os.path.basename(temp_path)}")
                if config.DEBUG_MODE:
                    print("DEBUG: Limpieza finalizada. "
                          f"{cleaned_count} eliminados.")

    if processed == 0 and file_count > 0:
        print("\nNo se procesó ningún archivo (verifique errores de lectura "
              "o formato).")
    elif not photo_data_list and processed > 0 and output_format != "update_exif":
        print("\nAnálisis completado, pero no se encontraron datos válidos "
              "para generar salida.")

    if config.DEBUG_MODE:
        print(f"DEBUG: [process_folder] === Fin process_folder ({output_format}) ===")


# --- Fluxo Principal de Execução ---
if __name__ == "__main__":
    if config.DEBUG_MODE:
        print("DEBUG: Iniciando __main__")

    print("\n--- Extractor/Actualizador Coordenadas y Descripciones EXIF v2.0 ---")
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
        if config.DEBUG_MODE:
            print(f"DEBUG: Carpeta ingresada (limpia): '{cleaned_folder}'")
        if os.path.isdir(cleaned_folder):
            selected_folder = cleaned_folder
            if config.DEBUG_MODE:
                print("DEBUG: La ruta es un directorio válido.")
            break
        else:
            print(f"\nError: La ruta '{cleaned_folder}' no es una carpeta "
                  "válida o no existe.")

    print("\nSelecciona la operación a realizar:")
    print("  --- Generar Archivos ---")
    print("  1: KMZ (Google Earth, fotos embebidas, usa Descripcion/Nome)")
    print("  2: CSV (Tabla de datos, incluye Nome y Descripcion)")
    print("  3: Excel (Tabla con fotos, Nome, y Descripcion editable)")
    print("  --- Actualizar Fotos ---")
    print("  4: Actualizar EXIF desde Excel (Lee Excel, escribe Descripcion)")
    print("  --- Otros Formatos ---")
    print("  5: KML Simple (My Maps, puntos y datos, SIN fotos, usa Descripcion/Nome)")

    valid_options = {
        1: "kmz",
        2: "csv",
        3: "excel",
        4: "update_exif",
        5: "kml_simple"
    }
    selected_format = ""
    while True:
        try:
            choice_raw = input("Ingresa el número de la opción deseada: ")
            choice_num = int(choice_raw.strip())

            if choice_num in valid_options:
                chosen_format = valid_options[choice_num]
                if chosen_format == "update_exif" and piexif is None:
                    print("\nError: La librería 'piexif' es necesaria para esta "
                          "opción y no está instalada.")
                    print("       Por favor, instálala ('pip install piexif') "
                          "y reinicia el script.")
                else:
                    selected_format = chosen_format
                    if config.DEBUG_MODE:
                        print(f"DEBUG: Opción numérica: {choice_num} -> "
                              f"Formato/Acción: '{selected_format}'")
                    break
            else:
                print("Número de opción inválido. Inténtalo de nuevo.")
        except ValueError:
            print("Entrada inválida. Por favor, ingresa solo el número de la opción.")
        except Exception as e:
            print(f"Error inesperado al leer la opción: {e}")

    if selected_folder and selected_format:
        if config.DEBUG_MODE:
            print(f"\nDEBUG: Llamando process_folder("
                  f"folder='{selected_folder}', "
                  f"output_format='{selected_format}')...")
        process_folder(selected_folder, selected_format)
    else:
        print("\nError: No se pudo determinar la carpeta o el formato de salida.")

    print("\n--- Script Finalizado ---")
    if config.DEBUG_MODE:
        print("DEBUG: Fin __main__")

    # input("\nPresiona Enter para salir...")