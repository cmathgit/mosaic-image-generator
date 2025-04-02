import os
import shutil
import zipfile
from PIL import Image, ImageOps, UnidentifiedImageError
import logging
import datetime # Added for timestamping

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
INPUT_DIR = "tiles_input"
OUTPUT_DIR = "tiles_output"
ARCHIVE_NAME = "tiles_archive.zip" # Archive for *final* processed files
ARCHIVE_OUTPUT_DIR = "tiles_archive" # Archive for *pre-existing* output files
SUPPORTED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff')

# 6-Color Versatile Palette (plus Magenta) - RGB values
# These values might need tuning depending on the desired visual outcome.
COLOR_PALETTE = {
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "black": (30, 30, 30),  # Use dark gray instead of pure black for some detail
    "white": (230, 230, 230), # Use light gray instead of pure white
    "green": (0, 128, 0),
    "magenta": (255, 0, 255),
}

# --- Helper Functions ---

def adjust_image_color(image_path, output_path, color_name, target_rgb):
    """
    Adjusts the color of an image by converting it to grayscale and then
    colorizing it towards the target RGB color.

    Args:
        image_path (str): Path to the input image.
        output_path (str): Path to save the adjusted image.
        color_name (str): Name of the target color (used for logging).
        target_rgb (tuple): The target RGB color tuple (R, G, B).
    """
    try:
        with Image.open(image_path) as img:
            # Ensure image has an alpha channel for consistent processing if needed,
            # though colorize works on RGB primarily. Convert to RGB first.
            img_rgb = img.convert("RGB")

            # Convert to grayscale
            grayscale_img = ImageOps.grayscale(img_rgb)

            # Colorize the grayscale image
            # black=(0,0,0) maps black in grayscale to black
            # white=target_rgb maps white in grayscale to the target color
            colorized_img = ImageOps.colorize(grayscale_img, black=(0, 0, 0), white=target_rgb)

            # Brightness, Contrast, Gamma, HSL adjustments are complex to apply
            # universally to "match" a target color without more sophisticated
            # color mapping algorithms. This colorization provides a strong tint.
            # Further BCG/HSL adjustments could be added here if specific transforms are defined.

            colorized_img.save(output_path)
            logging.info(f"Created '{color_name}' version: {output_path}")

    except FileNotFoundError:
        logging.error(f"Input image not found: {image_path}")
    except UnidentifiedImageError:
        logging.error(f"Cannot identify image file (possibly corrupted or unsupported format): {image_path}")
    except Exception as e:
        logging.error(f"Failed to process image {image_path} for color {color_name}: {e}")

def create_archive(source_dir, archive_path):
    """
    Creates a zip archive from the contents of a directory.

    Args:
        source_dir (str): The directory whose contents will be archived.
        archive_path (str): The path for the output zip file.
    """
    try:
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(source_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Add file to zip, using arcname to avoid including the source_dir structure
                    arcname = os.path.relpath(file_path, source_dir)
                    zipf.write(file_path, arcname=arcname)
        logging.info(f"Successfully created archive: {archive_path}")
    except Exception as e:
        logging.error(f"Failed to create archive {archive_path}: {e}")

def get_directory_size(directory):
    """Calculates the total size of files in a directory (including subdirectories)."""
    total_size = 0
    try:
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isfile(item_path):
                try:
                    total_size += os.path.getsize(item_path)
                except OSError as e:
                    logging.warning(f"Could not get size of file {item_path}: {e}")
            elif os.path.isdir(item_path):
                total_size += get_directory_size(item_path) # Recursive call for subdirectories
    except FileNotFoundError:
        logging.warning(f"Directory not found for size calculation: {directory}")
        return 0
    except Exception as e:
        logging.error(f"Error calculating size for {directory}: {e}")
        return 0
    return total_size

def archive_existing_output(output_dir, archive_base_dir):
    """Archives the contents of the output directory with a timestamp."""
    if not os.path.exists(archive_base_dir):
        try:
            os.makedirs(archive_base_dir)
            logging.info(f"Created archive directory: {archive_base_dir}")
        except Exception as e:
            logging.error(f"Failed to create archive directory {archive_base_dir}: {e}")
            return False # Indicate failure

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Use the name of the directory being archived in the filename for clarity
    output_dir_name = os.path.basename(os.path.normpath(output_dir))
    archive_filename = f"{output_dir_name}_archive_{timestamp}.zip"
    archive_path = os.path.join(archive_base_dir, archive_filename)

    logging.info(f"Attempting to archive contents of '{output_dir}' to '{archive_path}'...")
    try:
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(output_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, output_dir)
                    zipf.write(file_path, arcname=arcname)
        logging.info(f"Successfully archived existing output to: {archive_path}")
        return True # Indicate success
    except Exception as e:
        logging.error(f"Failed to archive '{output_dir}' to '{archive_path}': {e}")
        return False # Indicate failure

def prepare_directories():
    """
    Checks input/output directories, handles existing output via user prompts,
    and prepares directories for processing.

    Returns:
        bool: True if setup is successful and the script should proceed, False otherwise.
    """
    # 1. Check Input Directory
    if not os.path.isdir(INPUT_DIR):
        logging.error(f"Input directory '{INPUT_DIR}' not found. Please create it and place image files inside.")
        return False

    try:
        input_files = os.listdir(INPUT_DIR)
    except OSError as e:
        logging.error(f"Could not read input directory '{INPUT_DIR}': {e}")
        return False

    image_files_found = any(f.lower().endswith(SUPPORTED_EXTENSIONS) for f in input_files)
    if not image_files_found:
        logging.error(f"No supported image files found in the input directory '{INPUT_DIR}'.")
        return False
    logging.info(f"Found image files in input directory '{INPUT_DIR}'.")


    # 2. Check and Prepare Output Directory
    output_dir_exists = os.path.isdir(OUTPUT_DIR)
    output_files = []
    if output_dir_exists:
        try:
            # Get all entries, check if they are files later
            output_entries = os.listdir(OUTPUT_DIR)
            output_files = [f for f in output_entries if os.path.isfile(os.path.join(OUTPUT_DIR, f))]
        except OSError as e:
            logging.error(f"Could not read output directory '{OUTPUT_DIR}': {e}")
            # Treat as potentially non-empty/problematic, user might need to resolve manually
            return False

    if output_dir_exists and output_files:
        file_count = len(output_files)
        logging.warning(f"Output directory '{OUTPUT_DIR}' exists and contains {file_count} file(s).")

        # Confirm removal
        while True:
            user_choice_remove = input("--> Remove existing files and continue? (Y/N): ").strip().upper()
            if user_choice_remove == 'Y':
                break
            elif user_choice_remove == 'N':
                logging.info("Script execution aborted by user (chose not to remove existing files).")
                return False
            else:
                print("    Invalid input. Please enter Y or N.")

        # Confirm archiving
        should_archive = False
        while True:
            user_choice_archive = input(f"--> Archive {file_count} existing files to '{ARCHIVE_OUTPUT_DIR}' before removing? (Y/N): ").strip().upper()
            if user_choice_archive == 'Y':
                should_archive = True
                break
            elif user_choice_archive == 'N':
                should_archive = False
                break
            else:
                print("    Invalid input. Please enter Y or N.")

        # Handle archiving logic
        if should_archive:
            if file_count > 200:
                dir_size_bytes = get_directory_size(OUTPUT_DIR)
                dir_size_mb = dir_size_bytes / (1024 * 1024) if dir_size_bytes > 0 else 0
                print(f"\n    Warning: Archiving {file_count} files.")
                print(f"    Estimated uncompressed size: {dir_size_mb:.2f} MB.")
                print(f"    This might take time and significant disk space depending on compression.")
                while True:
                    user_choice_proceed = input("--> Proceed with archiving? (Y/N): ").strip().upper()
                    if user_choice_proceed == 'Y':
                        break
                    elif user_choice_proceed == 'N':
                        logging.info("Archiving skipped by user due to size/time warning.")
                        should_archive = False
                        break
                    else:
                        print("    Invalid input. Please enter Y or N.")

            if should_archive:
                if not archive_existing_output(OUTPUT_DIR, ARCHIVE_OUTPUT_DIR):
                    logging.error("Archiving failed. Aborting script to prevent data loss.")
                    # Avoid removing files if archive failed
                    return False

        # Clear the output directory if removal was confirmed
        logging.info(f"Removing existing contents of '{OUTPUT_DIR}'...")
        try:
            shutil.rmtree(OUTPUT_DIR)
            logging.info(f"Successfully removed '{OUTPUT_DIR}'.")
        except Exception as e:
            logging.error(f"Failed to remove existing output directory '{OUTPUT_DIR}': {e}")
            return False # Stop execution if removal fails

    # Ensure output directory exists (either newly created or recreated after clearing)
    if not os.path.exists(OUTPUT_DIR):
        try:
            os.makedirs(OUTPUT_DIR)
            logging.info(f"Created output directory: {OUTPUT_DIR}")
        except Exception as e:
            logging.error(f"Failed to create output directory '{OUTPUT_DIR}': {e}")
            return False

    # If we reach here, output directory exists and is empty
    logging.info(f"Output directory '{OUTPUT_DIR}' is ready.")
    return True # Proceed with execution

# --- Main Execution ---

def main():
    """
    Main function to orchestrate the image processing and archiving.
    """
    # Perform initial checks and preparations
    if not prepare_directories():
        logging.info("Script prerequisites not met or aborted by user. Exiting.")
        return # Stop if preparation failed or user aborted

    processed_files_count = 0
    processed_successfully = True # Flag to track if any processing step failed

    # 3. Process Each Image
    try:
        input_filenames = os.listdir(INPUT_DIR)
    except OSError as e:
        logging.error(f"Cannot list files in input directory '{INPUT_DIR}' during processing: {e}")
        return # Cannot proceed if input dir is unreadable now

    for filename in input_filenames:
        base_name, ext = os.path.splitext(filename)
        if ext.lower() not in SUPPORTED_EXTENSIONS:
            # This is logged by prepare_directories already, but good to skip here too
            continue # Skip non-supported files identified during processing loop

        input_image_path = os.path.join(INPUT_DIR, filename)
        logging.info(f"Processing image: {filename}")

        # 3a. Copy Original
        original_output_path = os.path.join(OUTPUT_DIR, filename)
        try:
            shutil.copy2(input_image_path, original_output_path) # copy2 preserves metadata
            logging.info(f"Copied original: {original_output_path}")
        except Exception as e:
            logging.error(f"Failed to copy original file {filename}: {e}")
            processed_successfully = False # Mark failure
            continue # Skip processing colors if original can't be copied

        # 3b. Create Colorized Versions
        for color_name, target_rgb in COLOR_PALETTE.items():
            output_filename = f"{base_name}_{color_name}{ext}"
            output_image_path = os.path.join(OUTPUT_DIR, output_filename)
            # Assuming adjust_image_color logs its own errors
            adjust_image_color(input_image_path, output_image_path, color_name, target_rgb)

        processed_files_count += 1 # Count successfully initiated processing attempts

    # Final checks and actions based on processing results
    if not processed_successfully and processed_files_count > 0:
         logging.warning("Some errors occurred during image processing.")
    elif processed_files_count == 0:
        # This case should ideally be caught by prepare_directories, but double-check
        logging.warning("No supported image files were found or processed in the input directory.")
        # Output directory should be empty if nothing was processed, remove it.
        if os.path.exists(OUTPUT_DIR) and not os.listdir(OUTPUT_DIR):
             try:
                 os.rmdir(OUTPUT_DIR)
                 logging.info(f"Removed empty output directory: {OUTPUT_DIR}")
             except OSError as e:
                  logging.error(f"Could not remove empty output directory {OUTPUT_DIR}: {e}")
        return # Exit if nothing was processed

    # 4. Archive Results (only if processing happened)
    if processed_files_count > 0:
        logging.info(f"Processed {processed_files_count} image(s). Archiving results...")
        create_archive(OUTPUT_DIR, ARCHIVE_NAME) # Archives the *newly generated* files

    # 5. Optional Cleanup (uncomment to enable) - Consider if needed after archiving
    # try:
    #     shutil.rmtree(OUTPUT_DIR)
    #     logging.info(f"Cleaned up output directory: {OUTPUT_DIR}")
    # except Exception as e:
    #     logging.error(f"Failed to remove output directory {OUTPUT_DIR}: {e}")

    logging.info("Script finished.")

if __name__ == "__main__":
    main()
