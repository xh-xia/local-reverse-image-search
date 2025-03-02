# local-reverse-image-search

Given a local database of still images, search near-duplicates of a given input image using perceptual hashing.

# The pipeline/workflow of this Python script is as follows

1. ### Find perceptual hashes of all images in a given local image database.
   1. Preprocess images (Python package `Pillow`).
   2. Calculate binary perceptual hashes (e.g., Python package `ImageHash`).
   3. Store these image metadata in SQLite (standard Python package `sqlite3`).
2. ### Store these hashes in a spatial data partitioning tree.
   1. Build a BK-tree (Python package `pybktree`).
   2. (Optional) serialize the tree locally (otherwise build it from SQLite each time).
3. ### Search and/or Update the hash tree given any num of input images.
   - Search tree and output images (e.g., their file paths and file copies) that are near-duplicates for every given input image.
   - Calculate perceptual hashes of input images and update tree.

# How to run the script

Either run the script directly or build it into an executable.
Either way need to have a `params.json` file (will generate one on first run) in the script directory to specify:

- `db_dir`: SQLite db file directory.
- `img_dirs`: Image directories; can be more than one. This is the "image database" we want to index and search.
- `bk_dir`: BK-tree file directory.
- `input_dir`: Input image directory containing images to search/update.
- `operation`: Operation type: `build`, `search`, `update`, `find_duplicates`.
  - `build`: Build the SQLite db from image directories, and also the BK-tree. Will overwrite if db exists.
  - `search`: Search input images' near-duplicates in the database. Input images are those in `img_dirs`.
    - Say img1 is input image, img2, img3, and img4 are in the database, and say they are all near-duplicates (pairwise distance defined by `distance_method` within some threshold `distance_threshold`). Then This search will produce img2, img3, and img4, effectively finding near-duplicates in the database. However, to find all near-duplicates within the database itself without any input, use the `find_duplicates` operation.
  - `update`: Given existing database, update it according to "image database" in `img_dirs`; doesn't involve `input_dir`. If db doesn't exist, build first.
  - `find_duplicates`: Given existing database, (build bk-tree if it doesn't exist or reflect the database), find all the near-duplicates (what happens is for every image, we search (`O(log(n))`) the bk-tree for near-duplicates, thus finding all near-duplicates in `O(nlog(n))`).
- `hash_method`: Percetual hashing method (default to dhash).
- `hash_size`: Hash size of the perceptual hash.
- `distance_method`: Method to calculate the difference between two hashes (default to "hamming").
- `distance_threshold`

This project is inspired by [OurGuru's reverse image search repo](https://github.com/OurGuru/Offline-Reverse-Image-Search).
