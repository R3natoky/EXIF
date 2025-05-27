# -*- coding: utf-8 -*-
import os
import pandas as pd
import tempfile
from PIL import Image, UnidentifiedImageError
import traceback
from typing import List, Tuple, Dict, Any

import config
from core.utils import apply_orientation

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
