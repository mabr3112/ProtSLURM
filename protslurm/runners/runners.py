'''Module Containing python runners'''
# builtins
import logging
import os

# dependencies
import pandas as pd

# custom
from protslurm.poses import Poses
from protslurm.jobstarters import JobStarter

class RunnerOutput:
    '''RunnerOutput class handles how protein data is passed between Runners and Poses classes.'''
    def __init__(self, poses: Poses, results:pd.DataFrame, prefix:str, index_layers:int=0, index_sep:str="_"):
        self.results = self.check_data_formatting(results)
        # Remove layers if option is set
        if index_layers: self.results["select_col"] = self.results["description"].str.split(index_sep).str[:-1*index_layers].str.join(index_sep)
        else: self.results["select_col"] = self.results["description"]
        self.results = self.results.add_prefix(f"{prefix}_")
        self.poses = poses
        self.prefix = prefix

    def check_data_formatting(self, results:pd.DataFrame):
        '''Checks if the input DataFrame has the correct format.
        Needs to contain 'description' and 'location' columns.
        '''
        def extract_description(path):
            return os.path.splitext(os.path.basename(path))[0]

        mandatory_cols = ["description", "location"]
        if any(col not in results.columns for col in mandatory_cols): raise ValueError(f"Input Data to RunnerOutput class MUST contain columns 'description' and 'location'.\nDescription should carry the name of the poses, while 'location' should contain the path (+ filename and suffix).")
        if not (results['description'] == results['location'].apply(extract_description)).all(): raise ValueError(f"'description' column does not match 'location' column in runner output dataframe!")
        return results

    def return_poses(self):
        '''
        This method is intended to be used to integrate the output of a runner into a Poses class.
        Adds Output of a Runner class formatted in RunnerOutput into Poses.df. Returns Poses class.'''    
        startlen = len(self.results.index)

        # merge DataFrames
        if any(x in list(self.poses.df.columns) for x in list(self.results.columns)): logging.info(f"WARNING: Merging DataFrames that contain column duplicates. Column duplicates will be renamed!")
        merged_df = self.poses.df.merge(self.results, left_on="poses_description", right_on=f"{self.prefix}_select_col") # pylint: disable=W0201
        merged_df.drop(f"{self.prefix}_select_col", axis=1, inplace=True)
        merged_df.reset_index(inplace=True)

        # check if merger was successful:
        if len(merged_df) == 0: raise ValueError(f"Merging DataFrames failed. This means there was no overlap found between poses.df['poses_description'] and results[new_df_col]")
        if len(merged_df) < startlen: raise ValueError(f"Merging DataFrames failed. Some rows in results[new_df_col] were not found in poses.df['poses_description']")

        # reset poses and poses_description column
        merged_df["poses"] = merged_df[f"{self.prefix}_location"]
        merged_df["poses_description"] = merged_df[f"{self.prefix}_description"]

        self.poses.df = merged_df

        return self.poses

class Runner:
    '''Abstract Runner baseclass handling interface between Runners and Poses.'''
    def __str__(self):
        raise NotImplementedError(f"Your Runner needs a name! Set in your Runner class: 'def __str__(self): return \"runner_name\"'")

    def run(self, poses:Poses, jobstarter:JobStarter, output_dir:str, options:str=None, pose_options:str=None) -> RunnerOutput:
        '''method that interacts with Poses to run jobs and send Poses the scores.'''
        raise NotImplementedError(f"Runner Method 'run' was not overwritten yet!")

def parse_generic_options(options: str, pose_options: str, sep="--") -> tuple[dict,list]:
    """
    Parses generic options and pose-specific options from two input strings, combining them into a single dictionary of options
    and a list of flags. Pose-specific options overwrite generic options in case of conflicts. Options are expected to be separated
    by a specified separator within each input string, with options and their values separated by spaces.

    Parameters:
    - options (str): A string of generic options, where different options are separated by the specified separator and each option's
      value (if any) is separated by space.
    - pose_options (str): A string of pose-specific options, formatted like the `options` parameter. These options take precedence
      over generic options.
    - sep (str, optional): The separator used to distinguish between different options in both input strings. Defaults to "--".

    Returns:
    - tuple: A 2-element tuple where the first element is a dictionary of merged options (key-value pairs) and the second element
      is a list of unique flags (options without values) from both input strings.

    Example:
    >>> parse_generic_options("--width 800 --height 600", "--color blue --verbose")
    ({'width': '800', 'height': '600', 'color': 'blue'}, ['verbose'])

    This function internally utilizes a helper function `tmp_parse_options_flags` to process each input string separately before
    merging the results, ensuring that pose-specific options and flags are appropriately prioritized and duplicates are removed.
    """
    def tmp_parse_options_flags(options_str: str, sep:str="--") -> tuple[dict, list]:
        '''parses split options '''
        if not options_str: return {}, []
        # split along separator
        firstsplit = [x.strip() for x in options_str.split(sep) if x]

        # parse into options and flags:
        opts = {}
        flags = []
        for item in firstsplit:
            if len((x := item.split())) > 1:
                opts[x[0]] = " ".join(x[1:])
            elif len((x := item.split("="))) > 1:
                opts[x[0]] = "=".join(x[1:])
            else:
                flags.append(x[0])

        return opts, flags

    # parse into options and flags:
    opts, flags = tmp_parse_options_flags(options, sep=sep)
    pose_opts, pose_flags = tmp_parse_options_flags(pose_options, sep=sep)

    # merge options and pose_options (pose_opts overwrite opts), same for flags
    opts.update(pose_opts)
    flags = list(set(flags) | set(pose_flags))
    return opts, flags
