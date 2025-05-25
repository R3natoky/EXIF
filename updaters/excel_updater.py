# -*- coding: utf-8 -*-
import os
import pandas as pd
import traceback # For debug mode if used within the function
from typing import Optional # Added for _decode_bytes_aggressively_for_debug type hint consistency

import config

# --- Dependência para Opção 4 (Actualizar EXIF) ---
try:
    import piexif
except ImportError:
    print("ERROR: La librería 'piexif' es necesaria para la opción de actualizar EXIF.")
    print("Por favor, instálala ejecutando: pip install piexif")
    piexif = None # type: ignore

# Importar función auxiliar de core.exif_reader
try:
    from core.exif_reader import _decode_bytes_aggressively_for_debug
except ImportError:
    print("WARN: No se pudo importar _decode_bytes_aggressively_for_debug desde core.exif_reader")
    def _decode_bytes_aggressively_for_debug(byte_string: Optional[bytes], tag_name_hint: str = "") -> Optional[str]: # type: ignore
        return f"(Fallback _decode_bytes_aggressively_for_debug: {repr(byte_string)})"


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
                exif_dict = piexif.load(image_path); # type: ignore
                if '0th' not in exif_dict: exif_dict['0th'] = {}
                if description_str_to_write:
                    exif_dict['0th'][piexif.ImageIFD.ImageDescription] = description_str_to_write.encode('utf-8') # type: ignore
                elif piexif.ImageIFD.ImageDescription in exif_dict.get('0th', {}): # type: ignore
                    del exif_dict['0th'][piexif.ImageIFD.ImageDescription] # type: ignore
                if custom_name_str_to_write:
                    exif_dict['0th'][config.NOME_PERSONALIZADO_TAG_ID] = custom_name_str_to_write.encode('utf-8')
                elif config.NOME_PERSONALIZADO_TAG_ID in exif_dict.get('0th', {}):
                    del exif_dict['0th'][config.NOME_PERSONALIZADO_TAG_ID]
                if config.DEBUG_MODE:
                    try:
                        temp_exif_bytes_debug = piexif.dump(exif_dict) # type: ignore
                        reloaded_temp_debug = piexif.load(temp_exif_bytes_debug) # type: ignore
                        artist_val_debug = reloaded_temp_debug.get("0th", {}).get(config.NOME_PERSONALIZADO_TAG_ID)
                        # Añadido \n para mejor formato si este log se activa
                        print(f"\nDEBUG [update_exif]: Valor 'Artist' en bytes dumpeados para '{filename}': {repr(artist_val_debug)} {_decode_bytes_aggressively_for_debug(artist_val_debug, 'Artist from dumped bytes')}") # type: ignore
                    except Exception as e_debug_dump: print(f"DEBUG [update_exif]: Error depurando dump para {filename}: {e_debug_dump}")
                exif_bytes = piexif.dump(exif_dict); piexif.insert(exif_bytes, image_path) # type: ignore
                updated_count += 1
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
