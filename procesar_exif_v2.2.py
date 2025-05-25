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
import math # Used by get_coordinates
import traceback # Used in process_folder
from typing import Optional, Dict, Any, Tuple, List, Union # Keep for existing type hints

import config # Importa nuestro módulo de configuración
from core.exif_reader import get_exif_data
from core.geo import dms_to_decimal, convert_to_utm
from core.utils import sanitize_filename # apply_orientation removed as it's not used directly here
from generators.csv_generator import _generate_csv
from generators.excel_generator import _generate_excel
from generators.kml_generator import _generate_kmz, _generate_kml_simple
from updaters.excel_updater import update_exif_from_excel

ImageFile.LOAD_TRUNCATED_IMAGES = True

# La dependencia piexif ha sido movida a updaters/excel_updater.py

# --- Funções Auxiliares ---

# La función get_coordinates es la única función auxiliar que permanece en este archivo.
# Otras funciones auxiliares como _decode_exif_string, dms_to_decimal, etc.,
# han sido movidas a sus respectivos módulos en `core/`.

def get_coordinates(exif_data: config.ExifData) -> config.Coordinates:
    """Extrae las coordenadas de latitud y longitud de los datos EXIF."""
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

# Todas las funciones generadoras de archivos (_generate_csv, _generate_excel, _generate_kmz, _generate_kml_simple)
# y la función de actualización EXIF (update_exif_from_excel) han sido movidas
# a sus respectivos módulos en los directorios `generators/` y `updaters/`.
# Las funciones auxiliares de decodificación, geográficas y de utilidades
# también han sido movidas a `core/exif_reader.py`, `core/geo.py` y `core/utils.py`.

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
    # La comprobación de piexif para la opción 4 se gestiona ahora dentro de update_exif_from_excel
    # y/o podría añadirse una advertencia aquí si se selecciona la opción 4 y piexif es None
    # (asumiendo que `piexif` ya no es una variable global en este archivo).
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
                # Para la opción 4 (update_exif), la función importada update_exif_from_excel
                # ahora contiene su propia comprobación de piexif.
                # Se podría añadir una comprobación aquí también para dar feedback inmediato al usuario.
                # Ejemplo:
                # if chosen_format == "update_exif":
                #     try:
                #         # Intentar importar piexif aquí solo para la comprobación temprana
                #         import piexif as piexif_check
                #         if piexif_check is None: raise ImportError
                #     except ImportError:
                #         print("\nError: La librería 'piexif' es necesaria para la opción 4 y no está instalada.")
                #         print("       Por favor, instálala ('pip install piexif') y reinicia el script.")
                #         continue # Vuelve a pedir la opción
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