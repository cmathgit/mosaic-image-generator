# Required libraries: pip install Pillow numpy scipy
from PIL import Image
import numpy as np
import os
from pathlib import Path
import zipfile
from scipy.spatial import KDTree
import sys # Import sys for stderr and exit
import datetime # Import datetime module
import configparser # Import configparser
import time # Import time for timing execution

# --- Configuration ---
TILE_SIZE = (50, 50) # Dimensions (width, height) in pixels for each tile image
GRID_RESOLUTION_FACTOR = 1.0 # Adjusts mosaic detail: 1.0 = standard, >1.0 = more tiles, <1.0 = fewer tiles

# --- Palette Definition ---
# Expanded 24-Color Professional Palette
PROFESSIONAL_PALETTE_HEX = {
    # Reds
    "Warm Red": "#E34234", "Cool Red": "#B22222", "Deep Red": "#8B0000", "Muted Red": "#CD5C5C",
    # Oranges
    "Vibrant Orange": "#F97306", "Earthy Orange": "#E97451",
    # Yellows
    "Cool Yellow": "#FFF44F", "Warm Yellow": "#F6A623", "Muted Yellow": "#C5A059",
    # Greens
    "Cool Green": "#008878", "Warm Green": "#507D2A", "Muted Green": "#808000", "Lush Green": "#50C878",
    # Blues
    "Warm Blue": "#3F51B5", "Cool Blue": "#00A6D6", "Muted Blue": "#6A7BA2", "Accent Blue": "#0077FF",
    # Purples
    "Warm Purple": "#6A0DAD", "Cool Purple": "#CCCCFF", "Muted Purple": "#915F6D",
    # Neutrals
    "White": "#FFFFFF", "Black": "#1C1C1C", "Warm Gray": "#404958", "Cool Gray": "#C0C0C0",
}

def hex_to_rgb(hex_color):
    """Converts a hex color string (e.g., #RRGGBB) to an (R, G, B) tuple."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        raise ValueError(f"Invalid hex color format: {hex_color}")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

# Convert palette hex codes to RGB tuples and store as a NumPy array
# Note: This palette is defined but not directly used in the mosaic color matching logic.
# Color matching is done based on the average colors of the provided tile images.
try:
    PALETTE_RGB = np.array([hex_to_rgb(hex_code) for hex_code in PROFESSIONAL_PALETTE_HEX.values()])
except ValueError as e:
    print(f"Error converting palette colors: {e}", file=sys.stderr)
    sys.exit(1) # Exit if palette is invalid

# --- Helper Functions ---

def get_average_rgb(image):
    """
    Calculates the average RGB color of a PIL Image object.

    Args:
        image (PIL.Image.Image): The input image.

    Returns:
        tuple: A tuple representing the average (R, G, B) color.
    """
    # Convert image to a NumPy array for efficient calculation
    img_array = np.array(image.convert('RGB'), dtype=float)
    # Calculate the mean color across all pixels (axis 0 and 1)
    avg_color = np.mean(img_array, axis=(0, 1))
    # Return as integer tuple
    return tuple(avg_color.astype(int))

def load_tile_images(source_path, tile_size):
    """
    Loads, resizes, and calculates average colors for tile images from a directory or zip file.

    Args:
        source_path (str): Path to the directory or zip file containing tile images.
        tile_size (tuple): Target size (width, height) for each tile.

    Returns:
        tuple: A tuple containing:
            - list: A list of resized PIL Image objects for the tiles.
            - numpy.ndarray: An array of average RGB colors corresponding to the tiles.

    Raises:
        ValueError: If the source path is invalid or no valid images are found.
    """
    tiles = []
    avg_colors = []

    # Use high-quality resampling filter
    resampling_filter = Image.Resampling.LANCZOS

    if os.path.isdir(source_path):
        print(f"Loading tiles from directory: {source_path}")
        # Load from a directory
        for filename in os.listdir(source_path):
            filepath = os.path.join(source_path, filename)
            # Basic check for image files
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff')):
                try:
                    img = Image.open(filepath).convert('RGB')
                    img = img.resize(tile_size, resampling_filter)
                    avg_color = get_average_rgb(img) # Already returns tuple
                    tiles.append(img)
                    avg_colors.append(avg_color)
                except Exception as e:
                    print(f"Warning: Skipping file {filename} due to error: {e}")

    elif zipfile.is_zipfile(source_path):
        print(f"Loading tiles from zip file: {source_path}")
        # Load from a zip file
        with zipfile.ZipFile(source_path, 'r') as zf:
            for filename in zf.namelist():
                # Basic check for image files within the zip
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff')) and not filename.startswith('__MACOSX'): # Ignore macOS metadata
                    try:
                        with zf.open(filename) as file_in_zip:
                            img = Image.open(file_in_zip).convert('RGB')
                            img = img.resize(tile_size, resampling_filter)
                            avg_color = get_average_rgb(img) # Already returns tuple
                            tiles.append(img)
                            avg_colors.append(avg_color)
                    except Exception as e:
                        print(f"Warning: Skipping file {filename} in zip due to error: {e}")
    else:
        raise ValueError(f"Invalid TILE_IMAGES_SOURCE: '{source_path}'. Must be a directory or a zip file.")

    if not tiles:
        raise ValueError("No valid tile images were loaded from the source.")

    # Return tiles and average colors (as a list of tuples)
    return tiles, avg_colors

def find_best_match_tile(target_avg_color, unique_color_kdtree, unique_colors_list, tiles, color_to_indices_map):
    """
    Finds the next available tile image from the group whose average color
    is closest to the target color, cycling through tiles within the group.

    Args:
        target_avg_color (tuple): The target (R, G, B) color for the grid cell.
        unique_color_kdtree (scipy.spatial.KDTree): KDTree built from unique average tile colors.
        unique_colors_list (list): List of unique average color tuples (R, G, B) corresponding to the KDTree.
        tiles (list): The master list of PIL Image tile objects.
        color_to_indices_map (dict): A dictionary mapping unique color tuples to
                                     {'indices': [list_of_tile_indices], 'next_idx': int}.

    Returns:
        PIL.Image.Image: The selected tile image.

    Raises:
        ValueError: If the tile list is empty or KDTree query fails unexpectedly.
    """
    try:
        # Query the KDTree for the index of the nearest unique color in unique_colors_list
        distance, unique_color_index = unique_color_kdtree.query(target_avg_color, k=1)
    except Exception as e:
       # Handle cases where the query might fail
       print(f"Error during KDTree query for target color {target_avg_color}: {e}", file=sys.stderr)
       # Fallback: Return the first tile of the first group as a last resort
       if tiles:
           if unique_colors_list:
               first_group_key = unique_colors_list[0]
               if first_group_key in color_to_indices_map:
                   first_group_indices = color_to_indices_map[first_group_key]['indices']
                   if first_group_indices:
                       # Note: This fallback does not advance the cycle counter.
                       return tiles[first_group_indices[0]]
           # If groups are empty or list is empty, return the very first tile
           return tiles[0]
       else:
           raise ValueError("Cannot find best match tile: Tile list is empty.")

    # Get the matched unique color tuple (which is the key for our map)
    matched_unique_color = unique_colors_list[unique_color_index]

    # Retrieve the group info (list of original indices and the next index pointer)
    # Use .get() for safer access, although the color should exist if KDTree returned it
    group_info = color_to_indices_map.get(matched_unique_color)
    if not group_info or not group_info['indices']:
        # Should not happen if KDTree worked correctly and groups were formed
        print(f"Warning: No tile group found for matched color {matched_unique_color}. Falling back.", file=sys.stderr)
        return tiles[0] # Fallback

    original_tile_indices = group_info['indices']
    current_group_idx = group_info['next_idx']

    # Select the actual tile index from the group list using the current counter
    selected_tile_original_index = original_tile_indices[current_group_idx]

    # Update (increment) the next index counter for this color group, wrapping around
    group_info['next_idx'] = (current_group_idx + 1) % len(original_tile_indices)

    # Return the selected tile image
    return tiles[selected_tile_original_index]


# --- Main Mosaic Generation Function ---

def generate_mosaic(base_image_path, tile_images_source, output_path, tile_size, grid_resolution_factor=1.0):
    """
    Generates a photo mosaic by matching tiles to regions of the base image based on
    average color, cycling through tiles with similar colors.

    Args:
        base_image_path (str): Path to the base image.
        tile_images_source (str): Path to the directory or zip file of tile images.
        output_path (str): Path to save the resulting mosaic image.
        tile_size (tuple): Desired size (width, height) for each tile.
        grid_resolution_factor (float): Multiplier for grid density. 1.0 is standard.
    """
    try:
        print("--- Starting Photo Mosaic Generation ---")

        # 1. Load Base Image
        print(f"1. Loading base image: {base_image_path}")
        base_image = Image.open(base_image_path).convert('RGB')
        base_width, base_height = base_image.size
        print(f"   Base image size: {base_width}x{base_height}")

        # 2. Load and Preprocess Tile Images
        print(f"2. Loading and processing tile images from: {tile_images_source}")
        # load_tile_images now returns avg_colors as a list of tuples
        tiles, tile_avg_colors_list = load_tile_images(tile_images_source, tile_size)
        print(f"   Loaded {len(tiles)} tile images.")

        if not tiles:
            raise ValueError("Tile loading resulted in an empty list.")

        # 3. Group Tiles by Average Color and Prepare for Cycling
        print("3. Grouping tiles by average color for cycling...")
        color_to_indices_map = {}
        for i, avg_color_tuple in enumerate(tile_avg_colors_list):
            # avg_color_tuple is already a tuple from get_average_rgb
            if avg_color_tuple not in color_to_indices_map:
                # Initialize group: list of original tile indices and next index pointer
                color_to_indices_map[avg_color_tuple] = {'indices': [], 'next_idx': 0}
            color_to_indices_map[avg_color_tuple]['indices'].append(i)

        if not color_to_indices_map:
            raise ValueError("Cannot group tiles: No average colors were processed.")

        # Extract unique colors and build KDTree from them
        unique_colors_list = list(color_to_indices_map.keys())
        unique_colors_array = np.array(unique_colors_list) # KDTree needs a NumPy array
        print(f"   Found {len(unique_colors_list)} unique average colors among tiles.")

        # 4. Build KDTree for Efficient Unique Color Matching
        print("4. Building KDTree from unique average colors...")
        if unique_colors_array.size == 0:
             raise ValueError("Cannot build KDTree: No unique average colors found.")
        # Check array dimension
        if unique_colors_array.ndim != 2 or unique_colors_array.shape[1] != 3:
             raise ValueError(f"Cannot build KDTree: Unique colors array has unexpected shape {unique_colors_array.shape}. Expected (N, 3).")

        unique_color_kdtree = KDTree(unique_colors_array)
        print("   KDTree built successfully.")

        # 5. Determine Grid and Prepare Base Image Analysis View
        print("5. Preparing base image grid analysis...")
        tile_w, tile_h = tile_size

        # Calculate grid dimensions based on base image size, tile size, and resolution factor
        grid_w = max(1, int(base_width / tile_w * grid_resolution_factor))
        grid_h = max(1, int(base_height / tile_h * grid_resolution_factor))

        print(f"   Calculated grid dimensions: {grid_w}x{grid_h}")

        # Create a small version of the base image matching the grid dimensions.
        # Getting the pixel color from this small image is equivalent to getting the
        # average color of the corresponding larger region in the original base image.
        # Use LANCZOS for high-quality downsampling.
        base_small_for_avg = base_image.resize((grid_w, grid_h), Image.Resampling.LANCZOS)

        # 6. Create Mosaic Canvas
        mosaic_width = grid_w * tile_w
        mosaic_height = grid_h * tile_h
        print(f"6. Creating mosaic canvas of size: {mosaic_width}x{mosaic_height}")
        mosaic_image = Image.new('RGB', (mosaic_width, mosaic_height))

        # 7. Assemble the Mosaic
        print("7. Assembling the mosaic (this may take time)...")
        processed_cells = 0
        total_cells = grid_w * grid_h
        for r in range(grid_h): # Iterate through grid rows
            for c in range(grid_w): # Iterate through grid columns
                # Get the average color of this grid cell from the downscaled base image
                cell_avg_color = base_small_for_avg.getpixel((c, r)) # Returns tuple (R,G,B)

                # Find the best matching tile using the new cycling logic
                best_tile = find_best_match_tile(
                    cell_avg_color,
                    unique_color_kdtree,
                    unique_colors_list,
                    tiles,
                    color_to_indices_map # Pass the map which includes cycle counters
                )

                # Calculate the position to paste the tile on the main canvas
                paste_x = c * tile_w
                paste_y = r * tile_h

                # Paste the selected tile
                mosaic_image.paste(best_tile, (paste_x, paste_y))

                processed_cells += 1
                # Optional: Print progress periodically
                if processed_cells % 100 == 0 or processed_cells == total_cells:
                    print(f"   Progress: {processed_cells}/{total_cells} cells processed ({((processed_cells/total_cells)*100):.1f}%)")

        print("   Mosaic assembly complete.")

        # 8. Save the Output
        print(f"8. Saving the final mosaic image to: {output_path}")
        # Ensure the output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        mosaic_image.save(output_path)
        print("--- Photo Mosaic Generation Finished Successfully ---")

    except FileNotFoundError as e:
        print(f"Error: Input file not found - {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: Configuration or data issue - {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
         print(f"Error: Missing required library. Please install Pillow, numpy, and scipy (`pip install Pillow numpy scipy`). Details: {e}", file=sys.stderr)
         sys.exit(1)
    except Exception as e:
        import traceback
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        print("Traceback:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

# --- Configuration Loading Function ---
def load_configuration(config_file='user_config.ini'):
    """Loads configuration from the specified INI file."""
    config = configparser.ConfigParser()

    # Define default values specific to this script's previous hardcoded values
    defaults = {
        'Paths': {
            'BASE_IMAGE_PATH': 'base_image.png',
            'TILE_IMAGES_SOURCE': 'tiles_archive.zip',
            'OUTPUT_DIRECTORY': 'mosaic_results'
        },
        'Parameters': {
            # Match the defaults previously in the __main__ block
            'TILE_SIZE': '50,50',
            'GRID_RESOLUTION_FACTOR': '7.0' # Default from CyclePhotos script
        }
    }
    config.read_dict(defaults) # Load defaults first

    if not os.path.exists(config_file):
        print(f"Warning: Configuration file '{config_file}' not found. Using default settings.", file=sys.stderr)
    else:
        try:
            config.read(config_file)
            print(f"Loaded configuration from '{config_file}'")
        except configparser.Error as e:
            print(f"Error reading configuration file '{config_file}': {e}. Using default settings.", file=sys.stderr)
            config.read_dict(defaults) # Re-load defaults on error

    # --- Extract and Validate Configuration ---
    settings = {}
    try:
        # Paths
        settings['BASE_IMAGE_PATH'] = config.get('Paths', 'BASE_IMAGE_PATH')
        settings['TILE_IMAGES_SOURCE'] = config.get('Paths', 'TILE_IMAGES_SOURCE')
        settings['OUTPUT_DIRECTORY'] = config.get('Paths', 'OUTPUT_DIRECTORY')

        # Parameters (with type conversion and validation)
        tile_size_str = config.get('Parameters', 'TILE_SIZE')
        try:
            settings['TILE_SIZE'] = tuple(map(int, tile_size_str.split(',')))
            if len(settings['TILE_SIZE']) != 2:
                 raise ValueError("TILE_SIZE must be two comma-separated integers.")
        except ValueError as e:
            print(f"Error parsing TILE_SIZE '{tile_size_str}': {e}. Using default ({defaults['Parameters']['TILE_SIZE']}).", file=sys.stderr)
            settings['TILE_SIZE'] = tuple(map(int, defaults['Parameters']['TILE_SIZE'].split(',')))

        try:
             settings['GRID_RESOLUTION_FACTOR'] = config.getfloat('Parameters', 'GRID_RESOLUTION_FACTOR')
        except ValueError:
             grid_res_default = defaults['Parameters']['GRID_RESOLUTION_FACTOR']
             print(f"Error parsing GRID_RESOLUTION_FACTOR. Using default ({grid_res_default}).", file=sys.stderr)
             settings['GRID_RESOLUTION_FACTOR'] = float(grid_res_default)

    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        print(f"Error accessing configuration option: {e}. Check '{config_file}'. Using defaults.", file=sys.stderr)
        # Revert to all defaults if fundamental structure is missing
        settings['BASE_IMAGE_PATH'] = defaults['Paths']['BASE_IMAGE_PATH']
        settings['TILE_IMAGES_SOURCE'] = defaults['Paths']['TILE_IMAGES_SOURCE']
        settings['OUTPUT_DIRECTORY'] = defaults['Paths']['OUTPUT_DIRECTORY']
        settings['TILE_SIZE'] = tuple(map(int, defaults['Parameters']['TILE_SIZE'].split(',')))
        settings['GRID_RESOLUTION_FACTOR'] = float(defaults['Parameters']['GRID_RESOLUTION_FACTOR'])

    return settings

def main():
    """Main execution function."""
    # Start timer
    start_time = time.time()

    # --- Load Configuration ---
    config = load_configuration('user_config.ini') # Load from INI file

    # --- Assign Variables from Config ---
    BASE_IMAGE_PATH = config['BASE_IMAGE_PATH']
    TILE_IMAGES_SOURCE = config['TILE_IMAGES_SOURCE']
    OUTPUT_DIRECTORY = config['OUTPUT_DIRECTORY']
    TILE_SIZE = config['TILE_SIZE']
    GRID_RESOLUTION_FACTOR = config['GRID_RESOLUTION_FACTOR']

    # --- Ensure Output Directory Exists ---
    output_dir_path = Path(OUTPUT_DIRECTORY)
    try:
        output_dir_path.mkdir(parents=True, exist_ok=True)
        print(f"Ensured output directory exists: {output_dir_path.resolve()}")
    except OSError as e:
         print(f"Error creating output directory {output_dir_path}: {e}", file=sys.stderr)
         return # Exit if cannot create directory

    # --- Generate Dynamic Output Path ---
    now = datetime.datetime.now()
    dt_string = now.strftime("%Y%m%d_%H%M%S")
    tile_size_str = f"{TILE_SIZE[0]}x{TILE_SIZE[1]}"
    grid_res_str = str(GRID_RESOLUTION_FACTOR).replace('.', 'p')
    # Add '_cycled' identifier for this script version
    output_filename = f"photo_mosaic_cycled_{dt_string}_tile{tile_size_str}_res{grid_res_str}.jpg"
    DYNAMIC_OUTPUT_PATH = output_dir_path / output_filename
    print(f"Output will be saved to: {DYNAMIC_OUTPUT_PATH}")

    # --- Validate Input Paths (Post-Config Load) ---
    if not os.path.exists(BASE_IMAGE_PATH):
        print(f"Error: Base image path '{BASE_IMAGE_PATH}' specified in config does not exist.", file=sys.stderr)
        return
    if not os.path.exists(TILE_IMAGES_SOURCE):
        print(f"Error: Tile images source path '{TILE_IMAGES_SOURCE}' specified in config does not exist.", file=sys.stderr)
        return

    # --- Run the Mosaic Generation ---
    generate_mosaic(
        base_image_path=BASE_IMAGE_PATH,
        tile_images_source=TILE_IMAGES_SOURCE,
        output_path=str(DYNAMIC_OUTPUT_PATH), # Pass path as string
        tile_size=TILE_SIZE,
        grid_resolution_factor=GRID_RESOLUTION_FACTOR
    )

    # End timer and print duration
    end_time = time.time()
    duration = end_time - start_time
    print(f"\nTotal execution time: {duration:.2f} seconds.")

# --- Execution Block ---
if __name__ == "__main__":
    main()
