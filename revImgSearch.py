"""
Reverse image search using perceptual hashing and BK-tree; for offline local image search.

getHashFunc() and isImage() use code from
https://github.com/JohannesBuchner/imagehash/blob/master/find_similar_images.py


Created: 5:02 PM (EST)
"""

import sys, os, json, sqlite3, pickle
from collections import namedtuple
from PIL import Image
import imagehash, pybktree, Levenshtein

CWD = os.path.abspath("")  # Current script path.
XBYTES = 1048576  # MiB to byte.
Img = namedtuple("Img", ["hash_hex", "directory", "filename"])  # Img class for bktree.


def main():
    #### 1. Parameters and ingredients alike.
    params = getParams()
    # hashFunc() is the runtime bottleneck; everything else is lightning fast.
    hashFunc = getHashFunc(method=params["hash_method"], hash_size=params["hash_size"])

    #### 2. Database #1: image metadata, including perceptual hash.
    if params["operation"] == "build":  # Build SQL database.
        buildDatabase(params, hashFunc)
    elif params["operation"] == "update":  # Update database: refresh it to only include all images in params["img_dirs"].
        updateDatabase(params, hashFunc)

    #### 3. Database #2: spatial data partitioning tree (BK-tree).
    # At this step img.db has been accessed, so it must exist, and thus we assume it exists.
    updateBKTree(params, dist_method=params["distance_method"])

    #### 4. Reverse image search.
    if params["operation"] == "search":
        1


# region SQL Functions


def buildDatabase(params, hashFunc):
    # This forces rebuild and overwrite existing db.
    createTable(params["db_dir"])
    for dir_ in params["img_dirs"]:
        fpaths = getAllImagePaths(dir_, relative=False)
        hashHex = [None] * len(fpaths)
        sizes = [None] * len(fpaths)
        for i, fpath in enumerate(fpaths):
            hashObj = hashFunc(getPILImage(fpath))
            hashHex[i] = str(hashObj)
            sizes[i] = os.path.getsize(fpath)  # In bytes.
            # assert len(hashHex[i]) == 16, f"Hex string ({hashHex[i]}) must have length of 16."
        rows = [(*os.path.split(p), h, s / XBYTES, True) for p, h, s in zip(fpaths, hashHex, sizes)]
        insertData2Table(rows, params["db_dir"])
    # displayTable(params["db_dir"])


def updateDatabase(params, hashFunc, dbname="img", del_absent=True):
    """
    For images in the existing db, remove ones that no longer exist in params["img_dirs"].
    For images not in the existing db but in params["img_dirs"], add them to db.
    End result: the new db has all images in params["img_dirs"], nothing more, nothing less.
    However, if del_absent=False, then the rows that are absent from params["img_dirs"] are retained.
    """
    dbname = os.path.join(params["db_dir"], f"{dbname}.db")
    if not os.path.isfile(dbname):  # db doesn't exist, build one and we are done here.
        buildDatabase(params, hashFunc)
        return
    # Otherwise db exists, we update it.
    con = sqlite3.connect(dbname)
    cur = con.cursor()
    cur.execute("UPDATE image SET present=FALSE;")
    con.commit()
    for dir_ in params["img_dirs"]:
        fpaths = getAllImagePaths(dir_, relative=False)
        for i, fpath in enumerate(fpaths):
            compKey = os.path.split(fpath)
            # Find image in db.
            res = cur.execute("SELECT directory FROM image WHERE directory=? AND filename=?;", compKey)
            if res.fetchone():  # Found image in db.
                cur.execute("UPDATE image SET present=TRUE WHERE directory=? AND filename=?;", compKey)
            else:  # Image is absent from db; insert it.
                hashObj = hashFunc(getPILImage(fpath))
                values = (*compKey, str(hashObj), os.path.getsize(fpath) / XBYTES, True)
                s = ",".join(["?"] * len(values))
                s = f"INSERT INTO image VALUES({s});"
                cur.execute(s, values)
    con.commit()

    if del_absent:  # Delete absent rows.
        cur.execute("DELETE FROM image WHERE present=FALSE;")
        con.commit()
    con.close()


def createTable(db_dir, dbname="img"):
    """
    Create image table. Filesize unit is MiB (chosen because we are dealing with normal images).
    MiB is Mebibyte, which is 1048576 bytes, or 1024 Kibibytes (KiB); 'tis binary-based unit. i stands for binary.
    If img.db already exists, delete and create a new one.
    """
    dbname = os.path.join(db_dir, f"{dbname}.db")
    if os.path.isfile(dbname):
        os.remove(dbname)  # Delete existing db file.

    con = sqlite3.connect(dbname)
    con.execute(
        """
        CREATE TABLE image(
            directory TEXT NOT NULL,  -- Full absolute path of the directory containing the file.
            filename TEXT NOT NULL,  -- File name, extension included.
            hash_hex TEXT,  -- In hex string.
            filesize NUMERIC,  -- In MiB.
            present BOOL,  -- Whether the row is present in params["img_dirs"].
            PRIMARY KEY(directory ASC, filename ASC)
            );
        """
    )
    con.close()


def insertData2Table(rows, db_dir, dbname="img"):
    if len(rows) == 0:
        return
    con = sqlite3.connect(os.path.join(db_dir, f"{dbname}.db"))
    cur = con.cursor()

    s = ",".join(["?"] * len(rows[0]))
    s = f"INSERT INTO image VALUES({s});"

    try:
        cur.executemany(s, rows)
    except:
        raise Exception

    con.commit()
    con.close()


def displayTable(db_dir, dbname="img"):
    con = sqlite3.connect(os.path.join(db_dir, f"{dbname}.db"))
    cur = con.cursor()
    res = cur.execute(
        """
        SELECT * FROM image
        """
    )
    res = res.fetchall()  # List.
    for r in res:
        print(r)

    con.commit()
    con.close()


# endregion


# region Tree and Distance Functions.


def buildBKTree(params, dbname="img", dist_method="hamming"):
    con = sqlite3.connect(os.path.join(params["db_dir"], f"{dbname}.db"))
    cur = con.cursor()
    res = cur.execute("SELECT hash_hex, directory, filename FROM image")
    imgs = map(Img._make, res.fetchall())
    con.commit()
    con.close()

    bk_tree = pybktree.BKTree(getStrDistFunc(method=dist_method), imgs)
    savePKL(params["bk_dir"], "bk_tree", bk_tree)


def updateBKTree(params, dbname="img", dist_method="hamming"):
    """
    1) If bk_tree.pkl doesn't exist, then build it.
    2) If bk_tree.pkl exists, load and then compare with img.db to make sure it has exactly every image in db. If not, then rebuild it.

    """
    if not os.path.isfile(os.path.join(params["bk_dir"], "bk_tree.pkl")):  # bk_tree doesn't exist, build it and done.
        print("Started building bk-tree because bk_tree.pkl doesn't exist.")
        buildBKTree(params, dbname=dbname, dist_method=dist_method)
        return

    # Get images (set of 3-namedtuple) from bk.
    imgs_bk = set(loadPKL(params["bk_dir"], "bk_tree"))

    # Get images (set of 3-namedtuple; even 3-tuple set check would work) from db.
    con = sqlite3.connect(os.path.join(params["db_dir"], f"{dbname}.db"))
    cur = con.cursor()
    res = cur.execute("SELECT hash_hex, directory, filename FROM image")
    imgs_db = set(map(Img._make, res.fetchall()))
    con.commit()
    con.close()

    # If the two sets are not equal, rebuild bk_tree and done.
    if imgs_bk != imgs_db:
        print(f"Started building bk-tree because bk_tree.pkl doesn't match {dbname}.db.")
        buildBKTree(params, dbname=dbname, dist_method=dist_method)


def add2BKTree(bk_tree, hash_hex, directory, filename):
    bk_tree.add(Img(hash_hex, directory, filename))


def findInBKTree(bk_tree, hash_hex, directory=None, filename=None, dist_thres=1):
    # Return a list of len-2 tuple: distance and Img class.
    # Since find only uses the hash_hex of the item and doesn't store anything, composite key is optional.
    return bk_tree.find(Img(hash_hex, directory, filename), dist_thres)


# endregion


# region Helper Functions


def searchByImages():
    1


def getParams():
    fpath = os.path.join(CWD, "params.json")
    if os.path.isfile(fpath):
        with open(fpath) as f:
            params = json.load(f)
    else:
        params = dict()
        params["db_dir"] = CWD
        params["img_dirs"] = [CWD]
        params["bk_dir"] = CWD
        params["input_dir"] = os.path.join(CWD, "input")
        params["operation"] = "update"
        params["hash_method"] = "dhash"
        params["hash_size"] = 8  # Same default as in imagehash.
        params["distance_method"] = "hamming"
        with open(fpath, "w") as f:
            json.dump(params, f, indent=4)
    return params


def getHashFunc(method="dhash", hash_size=8):
    """Return hashing function from imagehash.
    imagehash functions handle greyscaling and resizing, so we don't do them here.
    The returned function <hashFunc> only takes PIL.Image.Image instance.
    <hashFunc> returns imagehash.ImageHash object, which .
    """
    if method == "ahash":
        hashfunc = imagehash.average_hash
    elif method == "phash":
        hashfunc = imagehash.phash
    elif method == "dhash":
        hashfunc = imagehash.dhash
    elif method == "whash-haar":
        hashfunc = imagehash.whash
    elif method == "whash-db4":

        def hashfunc(img, **kwargs):
            return imagehash.whash(img, mode="db4", **kwargs)

    else:  # Default to dhash if method is undefined.
        hashfunc = imagehash.dhash

    # Below 2 methods are different from above and don't have hash_size param.
    # elif method == "colorhash":
    #     hashfunc = imagehash.colorhash
    # elif method == "crop-resistant":
    #     hashfunc = imagehash.crop_resistant_hash

    def hashFunc(img):
        return hashfunc(img, hash_size=hash_size)

    return hashFunc


def _hamming(str1, str2):
    return Levenshtein.hamming(str1.hash_hex, str2.hash_hex, pad=True)


def getStrDistFunc(method="hamming"):
    # Calculate distance between 2 strings (accessed via Img.hash_hex (namedtuple attribute)).
    if method == "hamming":
        return _hamming
    else:
        raise NotImplementedError(f"{method} is not implemented.")


def isImage(fname):
    f = fname.lower()
    return (
        f.endswith(".png")
        or f.endswith(".jpg")
        or f.endswith(".jpeg")
        or f.endswith(".bmp")
        or f.endswith(".gif")
        or ".jpg" in f
        or f.endswith(".svg")
    )


def getPILImage(fname):
    # Assume fname is a path to a valid image.
    # Comment out below if we don't make this assumption.
    # if not isImage(fname):
    #     return None
    return Image.open(fname)


def getAllImagePaths(top_dir, relative=True):
    # Default is top-down, and dirs and files are folders and files in the root dir.
    # Just need to iterate over all files, since os.walk goes through all dir and subdir.
    fnames = list()
    if relative:
        prefix_len = len(top_dir)
        for root, dirs, files in os.walk(top_dir):
            for file in files:
                if isImage(file):
                    fnames.append(os.path.join(root, file)[prefix_len:])
    else:
        for root, dirs, files in os.walk(top_dir):
            for file in files:
                if isImage(file):
                    fnames.append(os.path.join(root, file))

    return fnames


def savePKL(dir_out, fname, file):
    with open(os.path.join(dir_out, f"{fname}.pkl"), "wb") as f:
        pickle.dump(file, f)


def loadPKL(dir_in, fname):
    with open(os.path.join(dir_in, f"{fname}.pkl"), "rb") as f:
        file = pickle.load(f)
    return file


# endregion


if __name__ == "__main__":
    main()
