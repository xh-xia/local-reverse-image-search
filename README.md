# local-reverse-image-search

Given a local database of still images, search near-duplicates of a given input image using perceptual hashing.

# The pipeline/workflow of this Python script is as follows

1. ### Find perceptual hashes of all images in a given local image database.
   1. Preprocess images (Python package `Pillow`).
   2. Calculate binary perceptual hashes (e.g., Python package `ImageHash`).
   3. Store these image metadata in SQLite (Python package `sqlite3`).
2. ### Store these hashes in a spatial data partitioning tree.
   1. Build a BK-tree (Python package `pybktree`).
   2. (Optional) serialize the tree locally (otherwise build it from SQLite each time).
3. ### Search and/or Update the hash tree given any num of input images.
   - Search tree and output images (e.g., their file paths and file copies) that are near-duplicates for every given input image.
   - Calculate perceptual hashes of input images and update tree.

# How to run the script

Either run the script directly or build it into an executable.
Either way need to have a param.json file in the script directory to specify:

- SQLite db file directory.
- Image directories; can be more than one. This is the "image database" we want to index and search.
- (Optional) BK-tree file directory (default to SQLite above).
- (Optional) input image directory (default to script directory) containing images to search/update.
- (Optional) operation type: build, search, update (default to search).
  - build: Build the SQLite db from image directories, and also the BK-tree.
  - search: Search input image near-duplicates in the database.
  - update: For images we want to add/delete, we will update accordingly.
    - update-del: Delete images in input image directory from the database.
    - update-add: Add images in input image directory from the database.

This project is inspired by [OurGuru's reverse image search repo](https://github.com/OurGuru/Offline-Reverse-Image-Search).
