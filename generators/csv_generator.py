# -*- coding: utf-8 -*-
import os
import pandas as pd
import traceback
from typing import List

import config

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
