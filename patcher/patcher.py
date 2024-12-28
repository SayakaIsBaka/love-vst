import os
import sys
import shutil
import tempfile
import argparse
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED, ZipInfo
from diff_match_patch import diff_match_patch

main_patch = """@@ -2338,784 +2338,8 @@
 up()
-%0A%09--Steam integration%0A%09local os = love.system.getOS()%0A%09if os == 'OS X' or os == 'Windows' then %0A%09%09local st = nil%0A%09%09--To control when steam communication happens, make sure to send updates to steam as little as possible%0A%09%09if os == 'OS X' then%0A%09%09%09local dir = love.filesystem.getSourceBaseDirectory()%0A%09%09%09local old_cpath = package.cpath%0A%09%09%09package.cpath = package.cpath .. ';' .. dir .. '/?.so'%0A%09%09%09st = require 'luasteam'%0A%09%09%09package.cpath = old_cpath%0A%09%09else%0A%09%09%09st = require 'luasteam'%0A%09%09end%0A%0A%09%09st.send_control = %7B%0A%09%09%09last_sent_time = -200,%0A%09%09%09last_sent_stage = -1,%0A%09%09%09force = false,%0A%09%09%7D%0A%09%09if not (st.init and st:init()) then%0A%09%09%09love.event.quit()%0A%09%09end%0A%09%09--Set up the render window and the stage for the splash screen, then enter the gameloop with :update%0A%09%09G.STEAM = st%0A%09else%0A%09end
 %0A%0A%09-
@@ -2527,17 +2527,19 @@
 GER then
- 
+%0A%09%09
 G.SOUND_
@@ -2575,17 +2575,206 @@
 'stop'%7D)
- 
+%0A%09%09G.SOUND_MANAGER.channel:push(%7Btype = 'quit'%7D)%0A%09%09G.SOUND_MANAGER.thread:wait()%0A%09end%0A%0A%09if G.SAVE_MANAGER then%0A%09%09G.SAVE_MANAGER.channel:push(%7Btype = 'quit'%7D)%0A%09%09G.SAVE_MANAGER.thread:wait()%0A%09
 end%0A%09if 
"""

save_manager_patch = """@@ -3762,16 +3762,116 @@
 e_table)
+%0A%0A        --MOD: quit if receiving quit%0A        elseif request.type == 'quit' then%0A            break
 %0A       
"""

sound_manager_patch = """@@ -6750,32 +6750,131 @@
             end%0A
+        --MOD: quit if receiving quit%0A        elseif request.type == 'quit' then%0A            break%0A
         end%0A    
"""

patches = [
    {
        "file": "main.lua",
        "patch": main_patch
    },
        {
        "file": "engine/save_manager.lua",
        "patch": save_manager_patch
    },
        {
        "file": "engine/sound_manager.lua",
        "patch": sound_manager_patch
    },
]

# https://stackoverflow.com/a/35435548
class UpdateableZipFile(ZipFile):
    """
    Add delete (via remove_file) and update (via writestr and write methods)
    To enable update features use UpdateableZipFile with the 'with statement',
    Upon  __exit__ (if updates were applied) a new zip file will override the exiting one with the updates
    """

    class DeleteMarker(object):
        pass

    def __init__(self, file, mode="r", compression=ZIP_STORED, allowZip64=False):
        # Init base
        super(UpdateableZipFile, self).__init__(file, mode=mode,
                                                compression=compression,
                                                allowZip64=allowZip64)
        # track file to override in zip
        self._replace = {}
        # Whether the with statement was called
        self._allow_updates = False

    def writestr(self, zinfo_or_arcname, bytes, compress_type=None):
        if isinstance(zinfo_or_arcname, ZipInfo):
            name = zinfo_or_arcname.filename
        else:
            name = zinfo_or_arcname
        # If the file exits, and needs to be overridden,
        # mark the entry, and create a temp-file for it
        # we allow this only if the with statement is used
        if self._allow_updates and name in self.namelist():
            temp_file = self._replace[name] = self._replace.get(name,
                                                                tempfile.TemporaryFile())
            temp_file.write(bytes)
        # Otherwise just act normally
        else:
            super(UpdateableZipFile, self).writestr(zinfo_or_arcname,
                                                    bytes, compress_type=compress_type)

    def write(self, filename, arcname=None, compress_type=None):
        arcname = arcname or filename
        # If the file exits, and needs to be overridden,
        # mark the entry, and create a temp-file for it
        # we allow this only if the with statement is used
        if self._allow_updates and arcname in self.namelist():
            temp_file = self._replace[arcname] = self._replace.get(arcname,
                                                                   tempfile.TemporaryFile())
            with open(filename, "rb") as source:
                shutil.copyfileobj(source, temp_file)
        # Otherwise just act normally
        else:
            super(UpdateableZipFile, self).write(filename, 
                                                 arcname=arcname, compress_type=compress_type)

    def __enter__(self):
        # Allow updates
        self._allow_updates = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # call base to close zip file, organically
        try:
            super(UpdateableZipFile, self).__exit__(exc_type, exc_val, exc_tb)
            if len(self._replace) > 0:
                self._rebuild_zip()
        finally:
            # In case rebuild zip failed,
            # be sure to still release all the temp files
            self._close_all_temp_files()
            self._allow_updates = False

    def _close_all_temp_files(self):
        for temp_file in self._replace.values():
            if hasattr(temp_file, 'close'):
                temp_file.close()

    def remove_file(self, path):
        self._replace[path] = self.DeleteMarker()

    def _rebuild_zip(self):
        tempdir = tempfile.mkdtemp()
        try:
            temp_zip_path = os.path.join(tempdir, 'new.zip')
            with ZipFile(self.filename, 'r') as zip_read:
                # Create new zip with assigned properties
                with ZipFile(temp_zip_path, 'w', compression=self.compression,
                             allowZip64=self._allowZip64) as zip_write:
                    for item in zip_read.infolist():
                        # Check if the file should be replaced / or deleted
                        replacement = self._replace.get(item.filename, None)
                        # If marked for deletion, do not copy file to new zipfile
                        if isinstance(replacement, self.DeleteMarker):
                            del self._replace[item.filename]
                            continue
                        # If marked for replacement, copy temp_file, instead of old file
                        elif replacement is not None:
                            del self._replace[item.filename]
                            # Write replacement to archive,
                            # and then close it (deleting the temp file)
                            replacement.seek(0)
                            data = replacement.read()
                            replacement.close()
                        else:
                            data = zip_read.read(item.filename)
                        zip_write.writestr(item, data)
            # Override the archive with the updated one
            shutil.move(temp_zip_path, self.filename)
        finally:
            shutil.rmtree(tempdir)

def patch_file(file: str, patch: str, zipfile: UpdateableZipFile):
    filecontents = zipfile.read(file)
    dmp = diff_match_patch()
    patches = dmp.patch_fromText(patch)
    newtext, _ = dmp.patch_apply(patches, filecontents.decode())
    zipfile.writestr(file, newtext.encode(), ZIP_DEFLATED)

def main(args):
    if not os.path.isfile(args.filename):
        print(f"[!] Error: Specified file {args.filename} does not exist, exiting...")
        return 1
    shutil.copyfile(args.filename, "Balatro.love")
    with UpdateableZipFile("Balatro.love", "a") as zipfile:
        for p in patches:
            print(f"[i] Applying patches for {p['file']}...")
            patch_file(p["file"], p["patch"], zipfile)
    print("[+] All patches successfully applied!")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
                    prog='patcher.py',
                    description='Balatro patcher for VST, removes Steam requirement and fixes exiting threads on quit / restart')
    parser.add_argument('filename', help="file to patch")
    args = parser.parse_args()
    retcode = main(args)
    sys.exit(retcode)
