# --- START OF FILE procesar_exif_2.0.py ---
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Script para extraer coordenadas (Lat/Lon, UTM) y fecha de fotos EXIF.
# Genera archivos KMZ, CSV, Excel o KML simple. Optimiza tamaño para Excel.
# v2.0: Refatorado para PEP 8 (semicolons, line length, single-line blocks)
#       e limpeza de código. Funcionalidade da v1.8 mantida.
# -----------------------------------------------------------------------------

import os
# import sys  # Eliminado: No usado
from PIL import Image, ExifTags as PIL_ExifTags, ImageFile, UnidentifiedImageError
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

# --- Dependência para Opção 4 ---
try:
    import piexif
except ImportError:
    print("ERROR: La librería 'piexif' es necesaria para la opción 4 "
          "(Actualizar EXIF).")
    print("Por favor, instálala ejecutando: pip install piexif")
    piexif = None  # type: ignore

# --- MODO DE DEPURACIÓN ---
DEBUG_MODE = False
ImageFile.LOAD_TRUNCATED_IMAGES = True

# --- Constantes ---
if DEBUG_MODE:
    print("DEBUG: Definiendo constantes y diccionarios TAGS...")

_TAGS_INTERNAL = PIL_ExifTags.TAGS
TAGS: Dict[int, str] = {v: k for k, v in _TAGS_INTERNAL.items()}
GPSTAGS: Dict[int, str] = PIL_ExifTags.GPSTAGS

GPS_IFD_TAG_ID: int = TAGS.get("GPSInfo", 34853)
ORIENTATION_TAG_ID: int = TAGS.get("Orientation", 274)
IMAGE_DESCRIPTION_TAG_ID: int = TAGS.get("ImageDescription", 270)
DATETIME_ORIGINAL_TAG_ID: int = TAGS.get("DateTimeOriginal", 36867)
DATETIME_TAG_ID: int = TAGS.get("DateTime", 306)

EXCEL_IMAGE_COL: int = 0      # Coluna A
EXCEL_NAME_COL: int = 1       # Coluna B (Nova)
EXCEL_DESC_COL: int = 2       # Coluna C
EXCEL_DATA_START_COL: int = 1 # Dados textuais começam na coluna B (índice 1)

EXCEL_TARGET_IMAGE_WIDTH_PX: int = 250
EXCEL_TEMP_IMAGE_SCALE_FACTOR: float = 1.5
EXCEL_TEMP_IMAGE_QUALITY: int = 90
EXCEL_COL_WIDTH_FACTOR: float = 0.15
EXCEL_ROW_HEIGHT_FACTOR: float = 0.75

KMZ_IMAGE_WIDTH: int = 400
KMZ_IMAGE_QUALITY: int = 85

# --- Tipos para Type Hinting ---
ExifData = Dict[str, Any]
Coordinates = Optional[Tuple[float, float]]
UTMCoordinates = Optional[Tuple[float, float, int, str]]
PhotoInfo = Dict[str, Any]  # Inclui 'nome', 'filepath', 'orientation', etc.
Number = Union[int, float]

if DEBUG_MODE:
    print("DEBUG: Constantes y tipos definidos.")

# --- Funções Auxiliares ---

def _decode_exif_string(value: bytes) -> str:
    """Tenta decodificar um valor EXIF bytes para string."""
    try:
        # Tenta UTF-8 primeiro (mais comum)
        return value.decode('utf-8', 'strict').strip()
    except UnicodeDecodeError:
        try:
            # Fallback para Latin-1 (preserva bytes se não decodificar)
            return value.decode('latin-1', 'replace').strip()
        except Exception:
            # Fallback final se tudo falhar
            return repr(value)


def get_exif_data(image_path: str) -> Optional[Tuple[ExifData, Optional[int]]]:
    """
    Extrai dados EXIF de uma imagem, incluindo orientação e descrição.

    Retorna:
        Uma tupla (exif_data_decoded, orientation) ou (None, None) em caso de erro
        na leitura do arquivo, ou ({}, None) se o arquivo for lido mas não
        tiver EXIF ou houver erro ao ler o EXIF.
    """
    if DEBUG_MODE:
        print(f"\nDEBUG: [get_exif_data] Procesando: {os.path.basename(image_path)}")

    if not os.path.exists(image_path):
        print(f"\nError: Archivo no encontrado: {image_path}")
        return None, None

    exif_data_raw = None
    orientation: Optional[int] = None
    gps_info_raw = None
    exif_data_decoded: ExifData = {}

    try:
        with Image.open(image_path) as image:
            if DEBUG_MODE:
                print(f"DEBUG: [get_exif_data] Imagen "
                      f"'{os.path.basename(image_path)}' abierta.")
            try:
                exif_data_raw = image.getexif()
                if not exif_data_raw:
                    if DEBUG_MODE:
                        print(f"DEBUG: [get_exif_data] No hay datos EXIF en "
                              f"'{os.path.basename(image_path)}'.")
                    return {}, None  # EXIF vazio, mas arquivo lido
            except Exception as e_exif:
                # PNGs podem não ter o método getexif ou lançar erro específico
                if isinstance(e_exif, (AttributeError, TypeError)) and \
                   'PngImageFile' in str(type(image)):
                    if DEBUG_MODE:
                        print("DEBUG: [get_exif_data] No hay datos EXIF (PNG).")
                    return {}, None
                # Outros erros ao acessar EXIF
                print(f"\nWarning: No se pudo acceder a los datos EXIF para "
                      f"{os.path.basename(image_path)}: {e_exif}")
                return {}, None # Retorna dados vazios, indica problema no EXIF

            if exif_data_raw:
                if DEBUG_MODE:
                    print(f"DEBUG: [get_exif_data] Datos EXIF crudos obtenidos "
                          f"para '{os.path.basename(image_path)}'.")

                orientation = exif_data_raw.get(ORIENTATION_TAG_ID)

                try:
                    gps_info_raw = exif_data_raw.get_ifd(GPS_IFD_TAG_ID)
                except KeyError:
                    if DEBUG_MODE:
                        print("DEBUG: [get_exif_data] Tag GPSInfo (IFD) "
                              "no encontrada.")
                    gps_info_raw = None
                except Exception as e_gps:
                    print(f"\nWarning: Error accediendo a IFD GPS para "
                          f"{os.path.basename(image_path)}: {e_gps}")
                    gps_info_raw = None

                # Extrair Data/Hora
                raw_date = exif_data_raw.get(DATETIME_ORIGINAL_TAG_ID) or \
                           exif_data_raw.get(DATETIME_TAG_ID)
                date_str = None
                if raw_date and isinstance(raw_date, str):
                    clean_date = raw_date.replace('\x00', '').strip()
                    try:
                        # Validar formato antes de guardar
                        datetime.strptime(clean_date, '%Y:%m:%d %H:%M:%S')
                        date_str = clean_date
                    except ValueError:
                        print(f"\nWarning: Formato de fecha inválido "
                              f"'{clean_date}' en {os.path.basename(image_path)}")
                exif_data_decoded['DateTimeOriginal'] = date_str

                # Extrair Descrição da Imagem
                raw_desc = exif_data_raw.get(IMAGE_DESCRIPTION_TAG_ID)
                description = None
                if isinstance(raw_desc, str):
                    description = raw_desc.strip()
                elif isinstance(raw_desc, bytes):
                    description = _decode_exif_string(raw_desc)
                exif_data_decoded['ImageDescription'] = description

                # Processar outros tags EXIF
                skip_tags = {GPS_IFD_TAG_ID, ORIENTATION_TAG_ID,
                             IMAGE_DESCRIPTION_TAG_ID, DATETIME_ORIGINAL_TAG_ID,
                             DATETIME_TAG_ID}
                for tag_id, value in exif_data_raw.items():
                    if tag_id in skip_tags or tag_id is None:
                        continue
                    tag_name = TAGS.get(tag_id, f"Unknown_{tag_id}")
                    if isinstance(value, bytes):
                        decoded_value = _decode_exif_string(value)
                        # Evitar mostrar dados binários muito longos
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

                # Processar dados GPS se existirem
                if gps_info_raw:
                    gps_data: Dict[str, Any] = {}
                    for gps_id, gps_val in gps_info_raw.items():
                        if gps_id is None:
                            continue
                        gps_name = GPSTAGS.get(gps_id, f"UnknownGPS_{gps_id}")

                        if isinstance(gps_val, bytes):
                            try:
                                # Tentar ASCII primeiro para refs (N, S, E, W)
                                decoded_gps = gps_val.decode('ascii', 'strict').strip()
                            except UnicodeDecodeError:
                                decoded_gps = _decode_exif_string(gps_val)
                            gps_data[gps_name] = decoded_gps
                        elif isinstance(gps_val, tuple) and gps_val:
                            # Tentar converter tupla para números (DMS)
                            try:
                                numeric_tuple = tuple(
                                    float(getattr(v, 'real', v)) for v in gps_val
                                )
                                if all(math.isfinite(n) for n in numeric_tuple):
                                    gps_data[gps_name] = numeric_tuple
                                else:
                                    if DEBUG_MODE:
                                        print("DEBUG: GPS tuple contem "
                                              f"não-finitos: {gps_val}")
                                    gps_data[gps_name] = repr(gps_val)
                            except (ValueError, TypeError):
                                if DEBUG_MODE:
                                    print("DEBUG: GPS tuple não numérico: "
                                          f"{gps_val}")
                                gps_data[gps_name] = repr(gps_val)
                        elif isinstance(gps_val, (int, float)):
                            # Armazenar números diretamente (Altitude, etc.)
                            if math.isfinite(gps_val):
                                gps_data[gps_name] = float(gps_val)
                            else:
                                gps_data[gps_name] = repr(gps_val)
                        else:
                            gps_data[gps_name] = gps_val # Outros tipos

                    if gps_data:
                        exif_data_decoded["GPSInfo"] = gps_data

                return exif_data_decoded, orientation
            else:
                # Arquivo lido, mas exif_data_raw estava vazio
                return {}, None

    except FileNotFoundError:
        # Este erro já foi tratado no início, mas por segurança
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
        if DEBUG_MODE:
            traceback.print_exc()
        return None, None


def dms_to_decimal(degrees: Number, minutes: Number, seconds: Number,
                   direction: str) -> float:
    """
    Convierte Grados, Minutos, Segundos (DMS) a Grados Decimales.
    Lança ValueError em caso de erro de conversão ou direção inválida.
    """
    try:
        # Converte para float, lidando com tipos Racional se presentes
        deg_f = float(getattr(degrees, 'real', degrees))
        min_f = float(getattr(minutes, 'real', minutes))
        sec_f = float(getattr(seconds, 'real', seconds))

        # Verifica se são números finitos
        if not all(math.isfinite(x) for x in [deg_f, min_f, sec_f]):
            raise ValueError(f"Componente(s) DMS no finito: D={degrees}, "
                             f"M={minutes}, S={seconds}")

        # Verifica ranges (avisa mas continua)
        if not (0 <= min_f < 60 and 0 <= sec_f < 60):
            print(f"\nWarning: Valores DMS fuera del range (Min={min_f}, "
                  f"Sec={sec_f}), continuando cálculo.")

        # Fórmula de conversão
        dd = deg_f + min_f / 60.0 + sec_f / 3600.0

        # Aplica sinal baseado na direção
        direction_upper = direction.upper()
        if direction_upper in ['S', 'W']:
            return -dd
        elif direction_upper in ['N', 'E']:
            return dd
        else:
            raise ValueError(f"Dirección GPS desconocida: '{direction}'")

    except (ValueError, TypeError, AttributeError) as e:
        # Re-levanta como ValueError para sinalizar falha na conversão
        raise ValueError(f"Error convirtiendo DMS ({degrees}, {minutes}, "
                         f"{seconds}, {direction}): {e}") from e


def get_coordinates(exif_data: ExifData) -> Coordinates:
    """
    Extrae Latitud y Longitud de los datos EXIF procesados.
    Retorna una tupla (latitude, longitude) o None si faltan datos,
    son inválidos o ocurre un error.
    """
    if not exif_data or "GPSInfo" not in exif_data:
        return None
    gps = exif_data["GPSInfo"]

    # Obter os componentes DMS e as referências N/S/E/W
    lat_dms = gps.get("GPSLatitude")
    lat_ref = gps.get("GPSLatitudeRef")
    lon_dms = gps.get("GPSLongitude")
    lon_ref = gps.get("GPSLongitudeRef")

    # Validar existência e tipo básico dos dados essenciais
    if not (lat_dms and lat_ref and lon_dms and lon_ref):
        if DEBUG_MODE:
            print("DEBUG: [get_coordinates] Faltan tags GPS esenciales.")
        return None
    if not isinstance(lat_ref, str) or not isinstance(lon_ref, str):
        if DEBUG_MODE:
            print(f"DEBUG: [get_coordinates] Refs GPS no son strings: "
                  f"LatRef={type(lat_ref)}, LonRef={type(lon_ref)}")
        return None
    if not isinstance(lat_dms, tuple) or len(lat_dms) != 3:
        if DEBUG_MODE:
            print(f"DEBUG: [get_coordinates] Lat DMS inválido: {lat_dms}")
        return None
    if not isinstance(lon_dms, tuple) or len(lon_dms) != 3:
        if DEBUG_MODE:
            print(f"DEBUG: [get_coordinates] Lon DMS inválido: {lon_dms}")
        return None

    # Validar que os componentes DMS são numéricos
    try:
        _ = [float(getattr(v, 'real', v)) for v in lat_dms]
        _ = [float(getattr(v, 'real', v)) for v in lon_dms]
    except (ValueError, TypeError):
        if DEBUG_MODE:
            print(f"DEBUG: [get_coordinates] Conteúdo DMS não numérico: "
                  f"LAT={lat_dms}, LON={lon_dms}")
        return None

    # Tentar a conversão DMS para Decimal
    try:
        latitude = dms_to_decimal(lat_dms[0], lat_dms[1], lat_dms[2], lat_ref)
        longitude = dms_to_decimal(lon_dms[0], lon_dms[1], lon_dms[2], lon_ref)

        # Validar range das coordenadas calculadas
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            print(f"\nWarning: Coordenadas calculadas fuera de rango: "
                  f"Lat={latitude:.7f}, Lon={longitude:.7f}")
            return None

        return latitude, longitude

    except ValueError as e:
        # Erro durante a conversão DMS (já logado em dms_to_decimal)
        print(f"\nError procesando coordenadas DMS: {e}")
        return None
    except Exception as e_gen:
        # Erro inesperado nesta função
        print(f"\nError inesperado en get_coordinates: {e_gen}")
        if DEBUG_MODE:
            traceback.print_exc()
        return None


def convert_to_utm(latitude: float, longitude: float) -> UTMCoordinates:
    """
    Convierte coordenadas Lat/Lon (WGS84) a UTM (Este, Norte, Zona, Hemisferio).
    Retorna (easting, northing, zone, hemisphere) ou (None, None, None, None).
    """
    # Validação de tipo e range
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
        # Calcular zona UTM
        zone = math.floor((longitude + 180) / 6) + 1
        # Determinar hemisfério e código EPSG base
        hemisphere = 'N' if latitude >= 0 else 'S'
        epsg_code_base = 32600 if latitude >= 0 else 32700
        epsg_code = epsg_code_base + zone

        # Definir CRSs e o transformador
        crs_wgs84 = pyproj.CRS("EPSG:4326")
        crs_utm = pyproj.CRS(f"EPSG:{epsg_code}")
        transformer = pyproj.Transformer.from_crs(crs_wgs84, crs_utm,
                                                  always_xy=True) # Lon, Lat -> E, N

        # Realizar a transformação
        easting, northing = transformer.transform(longitude, latitude)

        # Verificar se resultado é finito
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
        if DEBUG_MODE:
            traceback.print_exc()
        return None, None, None, None


def sanitize_filename(name: str) -> str:
    """Limpia un nombre de archivo eliminando caracteres inválidos y espacios."""
    # Remove caracteres inválidos em nomes de arquivo Windows/Unix
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    # Substitui espaços por underscores
    name = name.replace(' ', '_')
    # Trunca para evitar nomes excessivamente longos
    return name[:100]


def apply_orientation(image: Image.Image, orientation: Optional[int]) -> Image.Image:
    """Aplica a orientação EXIF a uma cópia da imagem PIL."""
    # Mapeamento do valor EXIF Orientation para ação PIL.Image.Transpose
    actions = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE, # FLIP_LEFT_RIGHT then ROTATE_270
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE, # FLIP_LEFT_RIGHT then ROTATE_90
        8: Image.Transpose.ROTATE_90,
    }
    transpose_action = actions.get(orientation)

    if transpose_action:
        original_mode = image.mode
        try:
            if DEBUG_MODE:
                print(f"DEBUG: [apply_orientation] Aplicando orientação "
                      f"{orientation} ({transpose_action.name})")

            # Aplica a transposição
            # Usar .transpose() que retorna nova imagem
            oriented_image = image.transpose(transpose_action)

            # Correção de modo se alterado (raro, mas pode ocorrer com P, LA)
            if oriented_image.mode != original_mode and \
               original_mode not in ('P', 'LA'):
                if DEBUG_MODE:
                    print("DEBUG: [apply_orientation] Modo mudou de "
                          f"{original_mode} para {oriented_image.mode}, "
                          "tentando reverter para RGB/RGBA")
                try:
                    # Tenta converter de volta para RGB ou RGBA
                    if 'A' in oriented_image.mode:
                        oriented_image = oriented_image.convert('RGBA')
                    else:
                        oriented_image = oriented_image.convert('RGB')
                except Exception as e_conv:
                    print(f"\nWarning: Falha ao reconverter modo após "
                          f"orientação: {e_conv}")
                    # Retorna a imagem original se a conversão falhar
                    return image

            return oriented_image
        except Exception as e:
            print(f"\nWarning: Falha ao aplicar orientação EXIF {orientation}: {e}")
            # Retorna imagem original em caso de erro na orientação
            return image
    # Se não houver orientação ou for 1 (normal), retorna a original
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
            # Tenta ler a folha específica primeiro
            df = pd.read_excel(excel_path, sheet_name='Coordenadas_UTM_Data')
            print("  -> Hoja 'Coordenadas_UTM_Data' leída.")
        except ValueError: # Se a folha não existe
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

        # Verifica colunas necessárias (filename e Descripcion são chave aqui)
        required_cols = ['filename', 'Descripcion']
        if not all(col in df.columns for col in required_cols):
            print("\nError: El archivo Excel debe contener al menos las "
                  f"columnas: {', '.join(required_cols)}.")
            print(f"       Columnas encontradas: {list(df.columns)}")
            return

        total_rows = len(df)
        print(f"Procesando {total_rows} filas del Excel para actualizar EXIF...")

        for index, row in df.iterrows():
            current_row_num = index + 2 # Para referência de usuário (Excel é 1-based)
            filename_raw = row.get('filename')
            description_raw = row.get('Descripcion')

            # Pula linha se filename for inválido ou ausente
            if pd.isna(filename_raw) or \
               not isinstance(filename_raw, str) or \
               not filename_raw.strip():
                if DEBUG_MODE:
                    print(f"DEBUG: Fila {current_row_num} omitida "
                          "(filename inválido o ausente)")
                continue

            filename = filename_raw.strip()
            image_path = os.path.join(image_folder_path, filename)

            # Processa descrição (converte números para string, limpa)
            description_str = ""
            if not pd.isna(description_raw):
                if isinstance(description_raw, (int, float)):
                    description_str = str(description_raw).strip()
                elif isinstance(description_raw, str):
                    description_str = description_raw.strip()

            # Pula se a descrição final for vazia
            if not description_str:
                if DEBUG_MODE:
                    print(f"DEBUG: Fila {current_row_num} ('{filename}') "
                          "omitida (sin descripción válida).")
                skipped_no_desc += 1
                continue

            # Verifica se o arquivo de imagem existe
            if not os.path.isfile(image_path):
                print(f"\nWarning: Imagen no encontrada para fila "
                      f"{current_row_num} ('{filename}'), omitiendo "
                      "actualización.")
                skipped_no_file += 1
                continue

            # --- Atualização EXIF ---
            print(f"\rActualizando {index + 1}/{total_rows}: {filename}...",
                  end='', flush=True)
            try:
                # Carrega EXIF existente usando piexif
                exif_dict = piexif.load(image_path)

                # Garante que o dicionário IFD0 ('0th') existe
                if '0th' not in exif_dict:
                    exif_dict['0th'] = {}

                # Adiciona ou atualiza o tag ImageDescription
                # piexif espera bytes, UTF-8 é uma escolha segura
                if DEBUG_MODE and \
                   piexif.ImageIFD.ImageDescription not in exif_dict.get('0th', {}):
                    print(" [Tag ImageDescription ausente, será adicionado]", end='')

                exif_dict['0th'][piexif.ImageIFD.ImageDescription] = \
                    description_str.encode('utf-8')

                # Converte dicionário de volta para bytes EXIF
                exif_bytes = piexif.dump(exif_dict)
                # Insere os bytes EXIF atualizados na imagem
                piexif.insert(exif_bytes, image_path)
                updated_count += 1

            except FileNotFoundError:
                # Embora verificado antes, pode ocorrer race condition
                print(f"\nError interno (FileNotFound): Archivo '{filename}' "
                      "no encontrado durante actualización EXIF.")
                error_exif_update += 1
            except piexif.InvalidImageDataError:
                print(f"\nError EXIF: Datos de imagen inválidos o EXIF "
                      f"corrupto en '{filename}'. No se pudo actualizar.")
                error_exif_update += 1
            except ValueError as ve: # Erros comuns do piexif (e.g., tag inválido)
                print(f"\nError EXIF: Problema con datos EXIF existentes en "
                      f"'{filename}': {ve}. No se pudo actualizar.")
                error_exif_update += 1
            except OSError as oe: # Erros de I/O ao escrever
                print(f"\nError de Sistema al escribir EXIF en '{filename}': {oe}")
                error_exif_update += 1
            except Exception as e:
                print(f"\nError inesperado actualizando EXIF para '{filename}': {e}")
                if DEBUG_MODE:
                    traceback.print_exc()
                error_exif_update += 1
        # Fim do loop for
        print() # Nova linha após o \r

        # --- Resumo Final ---
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
        if DEBUG_MODE:
            traceback.print_exc()

# --- Funções para Geração de Saída ---

def _generate_kmz(photo_data_list: List[PhotoInfo], folder_name: str,
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
            # Não deve acontecer se a lista foi filtrada, mas por segurança
            print(f"\n   Skipping {filename}: Coordenadas inválidas ({lat}, {lon})")
            skipped_coords += 1
            continue

        # --- Define Nome do Ponto no KML ---
        # Prioridade: Descrição > Nome base > Nome do arquivo completo
        description = data.get('description')
        nome = data.get('nome') # Nome base sem extensão
        point_name = description or nome or filename

        # Cria o ponto KML (Longitude, Latitude)
        pnt = kml.newpoint(name=point_name, coords=[(lon, lat)])

        # Adiciona Timestamp se data disponível
        if data.get("photo_date"):
            try:
                dt = datetime.strptime(data['photo_date'], '%Y:%m:%d %H:%M:%S')
                # Formato KML/ISO 8601
                pnt.timestamp.when = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            except (ValueError, TypeError):
                # Ignora se data inválida (já avisado antes)
                pass # Expandido de linha única

        # --- Prepara Descrição HTML para o balão KML ---
        desc_html_parts = []
        if nome:
            desc_html_parts.append(f"<b>Nome:</b> {nome}")
        if description:
            desc_html_parts.append(f"<b>Descripción:</b> {description}")
        desc_html_parts.append(f"<b>Archivo:</b> {filename}")
        desc_html_parts.append(f"<b>Data:</b> {data.get('photo_date', 'N/A')}")

        # Formatar Coordenadas UTM
        utm_e_val = data.get('utm_easting')
        utm_n_val = data.get('utm_northing')
        utm_e = f"{utm_e_val:.2f}" if isinstance(utm_e_val, (int, float)) else 'N/A'
        utm_n = f"{utm_n_val:.2f}" if isinstance(utm_n_val, (int, float)) else 'N/A'
        utm_z = data.get('utm_zone', 'N/A')
        utm_h = data.get('utm_hemisphere', '')
        desc_html_parts.append(f"<b>UTM:</b> Zona {utm_z}{utm_h}, E: {utm_e}, N: {utm_n}")

        # --- Processa e Embuti Imagem no KMZ ---
        img_path = data.get('filepath')
        orientation = data.get('orientation')
        temp_img_path = None
        img_ref_in_kml = None # Referência do arquivo adicionado ao KML
        img_copy_kmz = None   # Imagem PIL processada

        if img_path and os.path.exists(img_path):
            try:
                with Image.open(img_path) as img_orig:
                    # Aplica orientação e cria cópia para redimensionar
                    img_oriented = apply_orientation(img_orig, orientation)
                    img_copy_kmz = img_oriented.copy()

                    # Redimensiona para largura alvo do KMZ
                    img_copy_kmz.thumbnail(
                        (KMZ_IMAGE_WIDTH, KMZ_IMAGE_WIDTH * 10), # Altura grande para manter proporção
                        Image.Resampling.LANCZOS
                    )

                    # Prepara para salvar como JPEG (formato comum para KMZ)
                    img_format_out = 'JPEG'
                    save_options = {'quality': KMZ_IMAGE_QUALITY, 'optimize': True}

                    # Converte modos complexos (P, RGBA, LA) para RGB antes de salvar
                    if img_copy_kmz.mode in ('P', 'RGBA', 'LA'):
                        if DEBUG_MODE:
                            print(f" [Convertendo modo {img_copy_kmz.mode} "
                                  "para RGB]", end="")
                        try:
                            # Cria fundo branco para transparência
                            background = Image.new("RGB", img_copy_kmz.size,
                                                   (255, 255, 255))
                            mask = None
                            if 'A' in img_copy_kmz.mode: # RGBA or LA
                                mask = img_copy_kmz.split()[-1]

                            # Converte para RGBA e depois RGB para colar com máscara
                            img_to_paste = img_copy_kmz.convert("RGBA").convert("RGB")
                            background.paste(img_to_paste, (0, 0), mask=mask)
                            img_copy_kmz.close() # Fecha a cópia original
                            img_copy_kmz = background # Usa a imagem com fundo
                        except Exception as e_conv_kmz:
                            print(f"\n   Warning: Falha ao converter imagem "
                                  f"{filename} para KMZ: {e_conv_kmz}")
                            img_copy_kmz.close()
                            img_copy_kmz = None # Sinaliza falha

                    # Salva a imagem processada em um arquivo temporário
                    if img_copy_kmz:
                        suffix = '.jpg'
                        # Cria arquivo temporário nomeado que persiste após fechar
                        with tempfile.NamedTemporaryFile(delete=False,
                                                         suffix=suffix,
                                                         prefix="kmz_") as tf:
                            temp_img_path = tf.name
                            img_copy_kmz.save(tf, format=img_format_out, **save_options)

                # Adiciona o arquivo temporário ao KML (simplekml copia para 'files/')
                if temp_img_path and os.path.exists(temp_img_path):
                    temps_to_delete.append(temp_img_path)
                    # addfile retorna a referência interna ao arquivo
                    img_ref_in_kml = kml.addfile(temp_img_path)

            except UnidentifiedImageError:
                print(f"\n   Warning: No se pudo identificar {filename} "
                      "como imagen para KMZ.")
            except Exception as e_img:
                print(f"\n   Warning: Error procesando imagen {filename} "
                      f"para KMZ: {e_img}")
            finally:
                # Garante que a cópia da imagem seja fechada
                if img_copy_kmz:
                    try:
                        img_copy_kmz.close()
                    except Exception:
                        pass # Falha ao fechar não é crítica aqui

        # --- Finaliza Descrição HTML ---
        # Junta as partes com <br/>
        desc_html = "<br/>".join(desc_html_parts)
        if img_ref_in_kml:
            # Usa a referência retornada por addfile para o src da imagem
            # simplekml organiza em 'files/'
            desc_html += (
                f'<hr/><img src="{img_ref_in_kml}" alt="Foto" '
                f'width="{KMZ_IMAGE_WIDTH}" />'
            )
        else:
            desc_html += '<hr/><i>Imagen no disponible o no embebida.</i>'
        pnt.description = desc_html
    # Fim do loop for
    print() # Nova linha após o \r

    if skipped_coords > 0:
        print(f"Aviso: {skipped_coords} puntos omitidos por coordenadas inválidas.")

    # Salva o arquivo KMZ final
    kmz_file = f"{out_base}.kmz"
    try:
        # savekmz lida com a criação do zip e da pasta 'files'
        kml.savekmz(kmz_file)
        print(f"\nArchivo KMZ guardado con éxito: {os.path.abspath(kmz_file)}")
        generated = True
    except Exception as e_save:
        print(f"\nERROR FATAL guardando KMZ {kmz_file}: {e_save}")
        traceback.print_exc()

    return generated, temps_to_delete


def _generate_csv(photo_data_list: List[PhotoInfo], out_base: str) -> bool:
    """Gera o arquivo CSV com os dados extraídos."""
    print("\nGenerando CSV...")
    generated = False
    try:
        df = pd.DataFrame(photo_data_list)

        # Selecionar e ordenar colunas desejadas para o CSV
        cols_to_include = [
            'nome', 'description', 'filename', 'photo_date',
            'latitude', 'longitude', 'utm_easting', 'utm_northing',
            'utm_zone', 'utm_hemisphere'
        ]
        # Garante que só incluímos colunas que realmente existem no DataFrame
        cols_in_df = [col for col in cols_to_include if col in df.columns]
        df_csv = df[cols_in_df].copy()

        # Formatar colunas numéricas como strings com precisão definida
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

        # Salvar CSV com codificação UTF-8 com BOM (melhor compatibilidade Excel)
        csv_file = f"{out_base}.csv"
        df_csv.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"\nArchivo CSV guardado con éxito: {os.path.abspath(csv_file)}")
        generated = True
    except Exception as e:
        print(f"\nERROR FATAL generando CSV: {e}")
        if DEBUG_MODE:
            traceback.print_exc()

    return generated


def _generate_excel(photo_data_list: List[PhotoInfo],
                    out_base: str) -> Tuple[bool, List[str]]:
    """Gera o arquivo Excel com dados e imagens redimensionadas."""
    print("\nGenerando Excel con imágenes (puede tardar)...")
    excel_file = f"{out_base}_con_fotos.xlsx"
    generated = False
    temps_to_delete: List[str] = []

    try:
        df = pd.DataFrame(photo_data_list)

        # --- Preparar DataFrame para a Saída Excel ---
        # Colunas de dados (texto) a serem incluídas e sua ordem
        # Começarão a partir da coluna B (índice 1) no Excel
        cols_data_order = [
            'Nome', 'Descripcion', 'filename', 'photo_date',
            'utm_easting', 'utm_northing', 'utm_zone', 'utm_hemisphere'
        ]
        df_out = pd.DataFrame() # DataFrame final para o Excel

        # Coluna B: Nome (derivado do filename, chave 'nome')
        if 'nome' in df.columns:
            # Preenche NaN com "" e garante string
            df_out['Nome'] = df['nome'].fillna("").astype(str)
        else:
            df_out['Nome'] = "" # Coluna vazia se 'nome' não existir

        # Coluna C: Descripcion (lida do EXIF ou vazia)
        if 'description' in df.columns:
            df_out['Descripcion'] = df['description'].fillna("").astype(str)
        else:
            df_out['Descripcion'] = ""

        # Coluna D: Filename (nome completo original)
        df_out['filename'] = df['filename']

        # Adiciona outras colunas se existirem, formatando as numéricas
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

        # Garante a ordem final das colunas de dados no DataFrame
        final_cols_data = [col for col in cols_data_order if col in df_out.columns]
        df_out = df_out[final_cols_data]

        # --- Escrever Excel e Inserir Imagens ---
        with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
            # Escreve os dados (df_out) a partir da coluna B (startcol=1)
            df_out.to_excel(writer, sheet_name='Coordenadas_UTM_Data',
                            startcol=EXCEL_DATA_START_COL, index=False)
            workbook = writer.book
            worksheet = writer.sheets['Coordenadas_UTM_Data']

            # --- Configurar Colunas ---
            # Define largura da Coluna A (índice 0) para a imagem
            worksheet.set_column(EXCEL_IMAGE_COL, EXCEL_IMAGE_COL,
                                 EXCEL_TARGET_IMAGE_WIDTH_PX * EXCEL_COL_WIDTH_FACTOR)
            # Opcional: Definir largura para Nome (Col B) e Descrição (Col C)
            worksheet.set_column(EXCEL_NAME_COL, EXCEL_NAME_COL, 25)
            worksheet.set_column(EXCEL_DESC_COL, EXCEL_DESC_COL, 40)

            # --- Loop para Processar e Inserir Imagens na Coluna A ---
            total = len(df) # Usa o DataFrame original 'df' que tem 'filepath'
            print("  -> Insertando imágenes en Excel...")
            for idx, row_data in df.iterrows():
                filename = row_data.get('filename', 'N/A')
                filepath = row_data.get('filepath')
                orientation = row_data.get('orientation')
                # Linha no Excel é idx + 1 (cabeçalho)
                excel_row_index = idx + 1

                print(f"\r     {idx + 1}/{total}: {filename[:40]}...",
                      end='', flush=True)

                # Pula se não houver caminho ou arquivo não existir
                if not filepath or not os.path.exists(filepath):
                    print(f"\n     Skipping image for row {excel_row_index}: "
                          f"File not found '{filepath}'")
                    # Define altura mínima da linha para não ficar esmagada
                    worksheet.set_row(excel_row_index, 15)
                    continue

                temp_img_path_excel = None # Caminho do arquivo temporário da imagem
                processed_image = None     # Objeto PIL da imagem processada

                try:
                    # Abre imagem original
                    with Image.open(filepath) as img_orig:
                        # Aplica orientação e cria cópia
                        img_oriented = apply_orientation(img_orig, orientation)
                        processed_image = img_oriented.copy()

                    w_orig, h_orig = processed_image.size
                    if w_orig == 0 or h_orig == 0:
                        raise ValueError("Dimensões inválidas da imagem.")

                    # Calcula dimensões do thumbnail temporário (maior que o final)
                    thumb_w = int(EXCEL_TARGET_IMAGE_WIDTH_PX *
                                  EXCEL_TEMP_IMAGE_SCALE_FACTOR)
                    thumb_h = int(h_orig * (thumb_w / w_orig))
                    processed_image.thumbnail((thumb_w, thumb_h * 2),
                                              Image.Resampling.LANCZOS)
                    final_w, final_h = processed_image.size # Tamanho após thumbnail

                    # Calcula fator de escala para inserir no Excel e altura da linha
                    scale_factor = EXCEL_TARGET_IMAGE_WIDTH_PX / final_w
                    row_height = (final_h * scale_factor) * EXCEL_ROW_HEIGHT_FACTOR + 5
                    worksheet.set_row(excel_row_index, row_height)

                    # Define formato e opções de salvamento
                    save_format = 'JPEG'
                    save_suffix = '.jpg'
                    save_options = {'quality': EXCEL_TEMP_IMAGE_QUALITY}

                    # PNG é melhor para modos com transparência ou paleta
                    if processed_image.mode in ('P', 'LA', 'RGBA'):
                        save_format = 'PNG'
                        save_suffix = '.png'
                        save_options = {'optimize': True}
                        # Converte P/LA para RGBA se necessário antes de salvar PNG
                        if processed_image.mode in ('P', 'LA'):
                            try:
                                if DEBUG_MODE:
                                    print(f" [Convertendo {processed_image.mode} "
                                          "para RGBA]", end="")
                                processed_image = processed_image.convert("RGBA")
                            except Exception as conv_e:
                                print(f"\n     Warning: Falha ao converter "
                                      f"{processed_image.mode}->RGBA para "
                                      f"{filename}: {conv_e}")
                                # Continua tentando salvar como PNG mesmo assim
                    elif processed_image.mode == 'CMYK':
                        # Excel geralmente não lida bem com CMYK, converte para RGB
                        try:
                            if DEBUG_MODE:
                                print(" [Convertendo CMYK para RGB]", end="")
                            processed_image = processed_image.convert("RGB")
                            # Volta para JPEG após converter para RGB
                            save_format = 'JPEG'
                            save_suffix = '.jpg'
                            save_options = {'quality': EXCEL_TEMP_IMAGE_QUALITY}
                        except Exception as conv_e:
                            print("\n     Warning: Falha ao converter CMYK->RGB "
                                  f"para {filename}: {conv_e}")
                            # Se falhar, não insere a imagem
                            raise ValueError("Não foi possível converter CMYK "
                                             f"para {filename}")

                    # Salva imagem processada em arquivo temporário
                    with tempfile.NamedTemporaryFile(delete=False,
                                                     suffix=save_suffix,
                                                     prefix="excel_") as tf:
                        temp_img_path_excel = tf.name
                        processed_image.save(tf, format=save_format, **save_options)

                    # Insere imagem no Excel se o arquivo temporário foi criado
                    if temp_img_path_excel and os.path.exists(temp_img_path_excel):
                        temps_to_delete.append(temp_img_path_excel)
                        insert_options = {
                            'x_scale': scale_factor,
                            'y_scale': scale_factor,
                            'object_position': 1 # Move com células
                        }
                        # Inserir na Coluna A (índice EXCEL_IMAGE_COL = 0)
                        worksheet.insert_image(excel_row_index, EXCEL_IMAGE_COL,
                                               temp_img_path_excel, insert_options)

                except UnidentifiedImageError:
                    print(f"\n     Warning: No se pudo identificar {filename} "
                          "como imagen para Excel.")
                    worksheet.set_row(excel_row_index, 15) # Altura mínima
                except ValueError as ve:
                    print(f"\n     Warning: Error de valor procesando imagen "
                          f"{filename} para Excel: {ve}")
                    worksheet.set_row(excel_row_index, 15)
                except Exception as img_e:
                    print(f"\n     Error procesando imagen {filename} para Excel "
                          f"(fila {excel_row_index}): {img_e}")
                    worksheet.set_row(excel_row_index, 15)
                finally:
                    # Garante fechar a imagem PIL processada
                    if processed_image:
                        try:
                            processed_image.close()
                        except Exception:
                            pass # Falha ao fechar não crítica
            # Fim do loop for
            print() # Nova linha após \r

        # Fim do bloco with pd.ExcelWriter
        print(f"\nArchivo Excel guardado con éxito: {os.path.abspath(excel_file)}")
        generated = True

    except Exception as e:
        print(f"\nERROR FATAL generando archivo Excel: {e}")
        if DEBUG_MODE:
            traceback.print_exc()

    return generated, temps_to_delete


def _generate_kml_simple(photo_data_list: List[PhotoInfo], folder_name: str,
                         out_base: str) -> bool:
    """
    Gera o arquivo KML simples (sem imagens embutidas), compatível com My Maps.
    """
    kml = simplekml.Kml(name=f"Coords {folder_name} (Simple)")
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

        # --- Define Nome do Ponto no KML ---
        description = data.get('description')
        nome = data.get('nome')
        point_name = description or nome or filename

        # Cria o ponto KML
        pnt = kml.newpoint(name=point_name, coords=[(lon, lat)])

        # Adiciona Timestamp se disponível
        if data.get("photo_date"):
            try:
                dt = datetime.strptime(data['photo_date'], '%Y:%m:%d %H:%M:%S')
                pnt.timestamp.when = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            except (ValueError, TypeError):
                pass # Ignora data inválida

        # --- Prepara Descrição HTML (sem imagem) ---
        desc_html_parts = []
        if nome:
            desc_html_parts.append(f"<b>Nome:</b> {nome}")
        if description:
            desc_html_parts.append(f"<b>Descripción:</b> {description}")
        desc_html_parts.append(f"<b>Archivo:</b> {filename}")
        desc_html_parts.append(f"<b>Data:</b> {data.get('photo_date', 'N/A')}")

        # Formatar UTM
        utm_e_val = data.get('utm_easting')
        utm_n_val = data.get('utm_northing')
        utm_e = f"{utm_e_val:.2f}" if isinstance(utm_e_val, (int, float)) else 'N/A'
        utm_n = f"{utm_n_val:.2f}" if isinstance(utm_n_val, (int, float)) else 'N/A'
        utm_z = data.get('utm_zone', 'N/A')
        utm_h = data.get('utm_hemisphere', '')
        desc_html_parts.append(f"<b>UTM:</b> Zona {utm_z}{utm_h}, E: {utm_e}, N: {utm_n}")

        pnt.description = "<br/>".join(desc_html_parts)
    # Fim do loop for
    print() # Nova linha após \r

    if skipped_coords > 0:
        print(f"Aviso: {skipped_coords} puntos omitidos por coordenadas inválidas.")

    # Salva o arquivo KML
    kml_file = f"{out_base}_simple.kml"
    try:
        kml.save(kml_file) # Salva como KML padrão (XML)
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
    if DEBUG_MODE:
        print(f"\nDEBUG: [process_folder] Iniciando para: '{folder_path}', "
              f"Formato: '{output_format.upper()}'")

    if not os.path.isdir(folder_path):
        print(f"Error: Carpeta no encontrada: {folder_path}")
        return

    # --- Caso Especial: Atualizar EXIF ---
    if output_format == "update_exif":
        excel_file_raw = input("\nIntroduce la ruta completa al archivo Excel "
                               "generado previamente (con las descripciones): ")
        # Limpa aspas e espaços da entrada
        excel_file_path = excel_file_raw.strip('"\' ')
        update_exif_from_excel(excel_file_path, folder_path)
        return # Termina após tentar atualizar

    # --- Geração de Arquivos de Saída ---
    print(f"\nProcesando imágenes en: {folder_path}")
    print(f"Formato de salida solicitado: {output_format.upper()}")

    photo_data_list: List[PhotoInfo] = [] # Lista para guardar dados válidos
    # Contadores para o resumo
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
        # Extensões de imagem suportadas (lowercase)
        img_ext = (".jpg", ".jpeg", ".tif", ".tiff", ".png")
        # Lista arquivos compatíveis na pasta, ordenados por nome
        entries = [entry for entry in os.scandir(folder_path)
                   if entry.is_file() and entry.name.lower().endswith(img_ext)]
        entries.sort(key=lambda x: x.name)
        file_count = len(entries)

        if file_count == 0:
            print("\nNo se encontraron archivos de imagen compatibles "
                  f"({', '.join(img_ext)}) en la carpeta.")
            return

        print(f"Encontrados {file_count} archivos de imagen. Analizando EXIF...")

        # Loop principal para processar cada imagem
        for idx, entry in enumerate(entries):
            filename = entry.name
            filepath = entry.path
            print(f"\rProcesando {idx + 1}/{file_count}: {filename:<50}",
                  end='', flush=True)

            # Extrai dados EXIF
            exif_result = get_exif_data(filepath)
            processed += 1

            # get_exif_data retorna None, None se arquivo não pôde ser lido
            if exif_result is None:
                errors_read += 1
                coords_nok += 1 # Assume sem coords/data se erro leitura
                date_nok += 1
                continue # Próximo arquivo

            exif_data, orientation = exif_result
            # Se retorna {}, None, arquivo lido mas EXIF vazio/inválido
            if not exif_data:
                coords_nok += 1 # Sem EXIF, sem coords/data
                date_nok += 1
                continue # Próximo arquivo

            # Extrai informações do dicionário EXIF decodificado
            photo_date = exif_data.get('DateTimeOriginal')
            description = exif_data.get('ImageDescription')
            # Extrai Nome Base (sem extensão) do filename
            base_name, _ = os.path.splitext(filename)
            nome = base_name

            # Atualiza contadores de data e descrição
            if photo_date:
                date_ok += 1
            else:
                date_nok += 1
            if description:
                desc_found += 1

            # Tenta obter coordenadas Lat/Lon
            coordinates = get_coordinates(exif_data)

            if coordinates:
                latitude, longitude = coordinates
                # Tenta converter para UTM
                utm_coords = convert_to_utm(latitude, longitude)

                # Se UTM válido, guarda todas as informações
                if utm_coords and all(val is not None for val in utm_coords):
                    easting, northing, zone, hemisphere = utm_coords
                    photo_info: PhotoInfo = {
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
                        'filepath': filepath, # Guarda caminho para usar depois
                        'orientation': orientation # Guarda orientação
                    }
                    photo_data_list.append(photo_info)
                    coords_ok += 1
                else:
                    # Falha na conversão UTM (erro já logado em convert_to_utm)
                    print(f"\n   Warning: Falha ao converter UTM para {filename} "
                          f"(Lat/Lon: {latitude:.5f}, {longitude:.5f})")
                    utm_err += 1
                    coords_nok += 1 # Conta como sem coords válidas no final
            else:
                # Coordenadas Lat/Lon não encontradas ou inválidas
                coords_nok += 1
        # Fim do loop for
        print() # Nova linha após \r

    except OSError as e:
        print(f"\nError de Sistema listando archivos en '{folder_path}': {e}")
        return
    except Exception as e_scan:
        print(f"\nError inesperado durante el escaneo de archivos: {e_scan}")
        if DEBUG_MODE:
            traceback.print_exc()
        return

    # --- Resumo do Processamento EXIF ---
    print("\n--- Resumen del Análisis EXIF ---")
    print(f"  - Archivos de imagen encontrados: {file_count}")
    print(f"  - Archivos procesados: {processed}")
    print(f"  - Errores de lectura de archivo/imagen: {errors_read}")
    print(f"  - Fotos con coordenadas Lat/Lon válidas: {coords_ok}")
    print(f"  - Fotos sin coordenadas válidas: {coords_nok}")
    if utm_err > 0: # Mostra só se houver erros UTM
        print(f"      - Fallos conversión UTM (de coords válidas): {utm_err}")
    print(f"  - Fotos con fecha válida: {date_ok}")
    print(f"  - Fotos sin fecha válida: {date_nok}")
    print(f"  - Fotos con descripción EXIF encontrada: {desc_found}")
    print("---------------------------------")

    # --- Geração da Saída ---
    if not photo_data_list:
        print("\nNo se encontraron fotos con coordenadas válidas suficientes "
              "para generar la salida.")
    else:
        print(f"\nSe encontraron {len(photo_data_list)} fotos con datos válidos.")
        print("Ordenando fotos por fecha (si disponible) y luego por nombre...")
        # Ordena usando data (ou string grande se ausente) e filename como desempate
        photo_data_list.sort(key=lambda item: (
            item.get("photo_date") or "9999", item["filename"]
        ))

        # Define nome base para os arquivos de saída
        folder_base_name = os.path.basename(os.path.normpath(folder_path))
        output_base_name = sanitize_filename(
            f"coordenadas_utm_{folder_base_name}_ordenado"
        )

        output_generated = False
        temp_files_to_clean: List[str] = []

        try:
            # Chama a função de geração apropriada
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
            # --- Limpeza de Arquivos Temporários ---
            if temp_files_to_clean:
                print(f"\nLimpiando {len(temp_files_to_clean)} archivos temporales...")
                cleaned_count = 0
                for temp_path in temp_files_to_clean:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                            cleaned_count += 1
                            if DEBUG_MODE:
                                print("  -> Eliminado: "
                                      f"{os.path.basename(temp_path)}")
                        except OSError as e_remove:
                            print(f"  Warning: No se pudo eliminar archivo "
                                  f"temporal '{temp_path}': {e_remove}")
                        except Exception as e_fatal:
                            print(f"  ERROR fatal eliminando temporal "
                                  f"'{temp_path}': {e_fatal}")
                    elif DEBUG_MODE:
                        print("  -> No encontrado para eliminar: "
                              f"{os.path.basename(temp_path)}")
                if DEBUG_MODE:
                    print("DEBUG: Limpieza finalizada. "
                          f"{cleaned_count} eliminados.")

    # --- Mensagem Final ---
    if processed == 0 and file_count > 0:
        print("\nNo se procesó ningún archivo (verifique errores de lectura "
              "o formato).")
    elif not photo_data_list and processed > 0 and output_format != "update_exif":
        # Só mostra se não estava atualizando EXIF
        print("\nAnálisis completado, pero no se encontraron datos válidos "
              "para generar salida.")

    if DEBUG_MODE:
        print(f"DEBUG: [process_folder] === Fin process_folder ({output_format}) ===")


# --- Fluxo Principal de Execução ---
if __name__ == "__main__":
    if DEBUG_MODE:
        print("DEBUG: Iniciando __main__")

    # Título do Script
    print("\n--- Extractor/Actualizador Coordenadas y Descripciones EXIF v2.0 ---")
    print("---                 (Lat/Lon & UTM)                      ---")
    print(f"--- Modo Depuración: {'ACTIVO' if DEBUG_MODE else 'INACTIVO'} ---")

    # Avisa se piexif não estiver disponível
    if piexif is None:
        print("\n*** ADVERTENCIA: La librería 'piexif' no está disponible. ***")
        print("***             La opción 4 (Actualizar EXIF) no funcionará. ***")
        print("***             Instálala con: pip install piexif          ***")

    # --- Seleção da Pasta ---
    selected_folder = ""
    while True:
        folder_raw = input("\nIntroduce la ruta completa a la carpeta con las fotos: ")
        cleaned_folder = folder_raw.strip('"\' ') # Limpa aspas e espaços
        if DEBUG_MODE:
            print(f"DEBUG: Carpeta ingresada (limpia): '{cleaned_folder}'")
        if os.path.isdir(cleaned_folder):
            selected_folder = cleaned_folder
            if DEBUG_MODE:
                print("DEBUG: La ruta es un directorio válido.")
            break # Sai do loop se a pasta for válida
        else:
            print(f"\nError: La ruta '{cleaned_folder}' no es una carpeta "
                  "válida o no existe.")

    # --- Seleção da Operação ---
    print("\nSelecciona la operación a realizar:")
    print("  --- Generar Archivos ---")
    print("  1: KMZ (Google Earth, fotos embebidas, usa Descripcion/Nome)")
    print("  2: CSV (Tabla de datos, incluye Nome y Descripcion)")
    print("  3: Excel (Tabla con fotos, Nome, y Descripcion editable)")
    print("  --- Actualizar Fotos ---")
    print("  4: Actualizar EXIF desde Excel (Lee Excel, escribe Descripcion)")
    print("  --- Otros Formatos ---")
    print("  5: KML Simple (My Maps, puntos y datos, SIN fotos, usa Descripcion/Nome)")

    # Mapeamento de escolha numérica para nome da ação
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
                # Verifica se piexif é necessário e está disponível
                if chosen_format == "update_exif" and piexif is None:
                    print("\nError: La librería 'piexif' es necesaria para esta "
                          "opción y no está instalada.")
                    print("       Por favor, instálala ('pip install piexif') "
                          "y reinicia el script.")
                    # Não sai do loop, permite escolher outra opção
                else:
                    selected_format = chosen_format
                    if DEBUG_MODE:
                        print(f"DEBUG: Opción numérica: {choice_num} -> "
                              f"Formato/Acción: '{selected_format}'")
                    break # Sai do loop de seleção de opção
            else:
                print("Número de opción inválido. Inténtalo de nuevo.")
        except ValueError:
            print("Entrada inválida. Por favor, ingresa solo el número de la opción.")
        except Exception as e:
            print(f"Error inesperado al leer la opción: {e}")

    # --- Executa Processamento ---
    if selected_folder and selected_format:
        if DEBUG_MODE:
            print(f"\nDEBUG: Llamando process_folder("
                  f"folder='{selected_folder}', "
                  f"output_format='{selected_format}')...")
        process_folder(selected_folder, selected_format)
    else:
        # Deve ocorrer apenas se o loop de seleção for interrompido de forma anormal
        print("\nError: No se pudo determinar la carpeta o el formato de salida.")

    print("\n--- Script Finalizado ---")
    if DEBUG_MODE:
        print("DEBUG: Fin __main__")

    # Descomentar para pausar no final se executado fora de um terminal persistente
    # input("\nPresiona Enter para salir...")

# --- END OF FILE procesar_exif_2.0.py ---