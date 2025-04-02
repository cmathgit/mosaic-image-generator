# Required libraries: pip install Pillow numpy scipy
from PIL import Image
import numpy as np
import os
from pathlib import Path
import zipfile
from scipy.spatial import KDTree
import sys # Import sys for stderr and exit
import datetime  # Import the datetime module
import time  # Import the time module
import configparser # Import configparser

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
                    avg_color = get_average_rgb(img)
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
                            avg_color = get_average_rgb(img)
                            tiles.append(img)
                            avg_colors.append(avg_color)
                    except Exception as e:
                        print(f"Warning: Skipping file {filename} in zip due to error: {e}")
    else:
        raise ValueError(f"Invalid TILE_IMAGES_SOURCE: '{source_path}'. Must be a directory or a zip file.")
        
    if not tiles:
        raise ValueError("No valid tile images were loaded from the source.")
        
    return tiles, np.array(avg_colors)

def find_best_match_tile(target_avg_color, tile_avg_colors_kdtree, tiles):
    """
    Finds the tile image with the average color closest to the target color.

    Args:
        target_avg_color (tuple): The target (R, G, B) color.
        tile_avg_colors_kdtree (scipy.spatial.KDTree): KDTree built from tile average colors.
        tiles (list): The list of PIL Image tile objects.

    Returns:
        PIL.Image.Image: The tile image that is the best match.
    """
    # Query the KDTree for the index of the nearest neighbor color
    # distance, index = tile_avg_colors_kdtree.query(target_avg_color, k=1) # k=1 finds the single nearest neighbor
    try:
      distance, index = tile_avg_colors_kdtree.query(target_avg_color, k=1) 
    except Exception as e:
      # Handle cases where the query might fail (e.g., empty tree, though checked earlier)
       print(f"Error during KDTree query for color {target_avg_color}: {e}")
       # As a fallback, return the first tile or handle error appropriately
       if tiles:
           return tiles[0] 
       else:
           raise ValueError("Cannot find best match tile: Tile list is empty.")

    return tiles[index]

# --- Main Mosaic Generation Function ---

def generate_mosaic(base_image_path, tile_images_source, output_path, tile_size, grid_resolution_factor=1.0):
    """
    Generates a photo mosaic by matching tiles to regions of the base image based on average color.

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
        tiles, tile_avg_colors = load_tile_images(tile_images_source, tile_size)
        print(f"   Loaded {len(tiles)} tile images.")
        
        # 3. Build KDTree for Efficient Color Matching
        print("3. Building KDTree for fast color matching...")
        if tile_avg_colors.size == 0:
             raise ValueError("Cannot build KDTree: No average colors calculated for tiles.")
        tile_color_kdtree = KDTree(tile_avg_colors)
        print("   KDTree built successfully.")

        # 4. Determine Grid and Prepare Base Image Analysis View
        print("4. Preparing base image grid analysis...")
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
        
        # 5. Create Mosaic Canvas
        mosaic_width = grid_w * tile_w
        mosaic_height = grid_h * tile_h
        print(f"5. Creating mosaic canvas of size: {mosaic_width}x{mosaic_height}")
        mosaic_image = Image.new('RGB', (mosaic_width, mosaic_height))
        
        # 6. Assemble the Mosaic
        print("6. Assembling the mosaic (this may take time)...")
        processed_cells = 0
        total_cells = grid_w * grid_h
        for r in range(grid_h): # Iterate through grid rows
            for c in range(grid_w): # Iterate through grid columns
                # Get the average color of this grid cell from the downscaled base image
                cell_avg_color = base_small_for_avg.getpixel((c, r))
                
                # Find the best matching tile using the KDTree
                best_tile = find_best_match_tile(cell_avg_color, tile_color_kdtree, tiles)
                
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

        # 7. Save the Output
        print(f"7. Saving the final mosaic image to: {output_path}")
        # Ensure the output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True) 
        mosaic_image.save(output_path)
        print("--- Photo Mosaic Generation Finished Successfully ---")

    except FileNotFoundError as e:
        print(f"Error: Input file not found - {e}", file=sys.stderr)
    except ValueError as e:
        print(f"Error: Configuration or data issue - {e}", file=sys.stderr)
    except ImportError as e:
         print(f"Error: Missing required library. Please install Pillow, numpy, and scipy (`pip install Pillow numpy scipy`). Details: {e}", file=sys.stderr)
    except Exception as e:
        import traceback
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        print("Traceback:", file=sys.stderr)
        traceback.print_exc()

def load_configuration(config_file='user_config.ini'):
    """Loads configuration from the specified INI file."""
    config = configparser.ConfigParser()
    
    # Define default values
    defaults = {
        'Paths': {
            'BASE_IMAGE_PATH': 'base_image.png',
            'TILE_IMAGES_SOURCE': 'tiles_archive.zip',
            'OUTPUT_DIRECTORY': 'mosaic_results'
        },
        'Parameters': {
            'TILE_SIZE': '50,50',
            'GRID_RESOLUTION_FACTOR': '4.2'
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
            print(f"Error parsing GRID_RESOLUTION_FACTOR. Using default ({defaults['Parameters']['GRID_RESOLUTION_FACTOR']}).", file=sys.stderr)
            settings['GRID_RESOLUTION_FACTOR'] = float(defaults['Parameters']['GRID_RESOLUTION_FACTOR'])

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
    if not os.path.exists(OUTPUT_DIRECTORY):
        try: # Add try-except for directory creation
            os.makedirs(OUTPUT_DIRECTORY)
            print(f"Created output directory: {OUTPUT_DIRECTORY}")
        except OSError as e:
            print(f"Error creating output directory {OUTPUT_DIRECTORY}: {e}", file=sys.stderr)
            return # Exit if cannot create directory

    # --- Generate Dynamic Output Path ---
    now = datetime.datetime.now()
    dt_string = now.strftime("%Y%m%d_%H%M%S")
    tile_size_str = f"{TILE_SIZE[0]}x{TILE_SIZE[1]}"
    grid_res_str = str(GRID_RESOLUTION_FACTOR).replace('.', 'p')
    output_filename = f"photo_mosaic_{dt_string}_tile{tile_size_str}_res{grid_res_str}.jpg"
    OUTPUT_PATH = os.path.join(OUTPUT_DIRECTORY, output_filename)
    print(f"Output will be saved to: {OUTPUT_PATH}")

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
        output_path=OUTPUT_PATH,
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
