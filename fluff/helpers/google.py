# This Helper contains code from Archiver, which was made by Roadcrosser.
# 🖤 If by any chance you're reading, we all miss you.
# https://github.com/Roadcrosser/archiver
import httplib2

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials

from helpers.sv_config import get_config

def authenticate():
    '''Return Google oAuth credentials'''
    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        "./fluff/data/service_account.json", "https://www.googleapis.com/auth/drive"
    )
    credentials.authorize(httplib2.Http())
    gauth = GoogleAuth()
    gauth.credentials = credentials
    return gauth

async def upload(ctx, file_path_no_ext, dotzip):
    '''Upload a log to Google Drive'''
    credentials = authenticate()
    drive = GoogleDrive(credentials)
    folder = get_config(ctx.guild.id, 'drive', 'folder')

    f = drive.CreateFile(
        {
            "parents": [{"kind": "drive#fileLink", "id": folder}],
            "title": file_path_no_ext + ".txt",
        }
    )
    with open(f"{file_path_no_ext}.txt", encoding='utf-8') as file:
        f.SetContentString(file.read())
        f.Upload()
    
    if dotzip:
        f_zip = drive.CreateFile(
            {
                "parents": [{"kind": "drive#fileLink", "id": folder}],
                "title": file_path_no_ext + " (files).zip",
            }
        )
        f_zip.content = dotzip
        f_zip["mimeType"] = "application/zip"
        f_zip.Upload()