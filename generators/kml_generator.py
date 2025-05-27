# -*- coding: utf-8 -*-
import os
import simplekml
import tempfile
from PIL import Image, UnidentifiedImageError
from datetime import datetime # For strptime
import traceback
from typing import List, Tuple, Dict, Any

import config
from core.utils import apply_orientation

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
