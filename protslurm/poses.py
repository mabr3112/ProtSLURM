"""
The 'poses' module in the ProtSLURM package is designed for running protein design tools, managing and manipulating protein data. 

It primarily focuses on handling proteins and their associated data represented as Pandas DataFrames. 
This module provides functionalities to parse, store, and manipulate protein data in various file formats, aiding in the management of complex protein study workflows. 

Key Features:
- Parsing protein data from different sources and formats.
- Storing and retrieving protein data in multiple file formats like JSON, CSV, Pickle, Feather, and Parquet.
- Integration with the ProtSLURM package for managing SLURM jobs, facilitating the handling of protein data in distributed computing environments.
- Advanced data manipulation capabilities, including merging and prefixing data from various sources.

Classes:
- Poses: A central class for storing and handling protein data frames. It supports various operations like setting up work directories, parsing protein data, and integrating outputs from different runners.

Dependencies:
- pandas: Used for DataFrame operations.
- protslurm: Required for job management and integrating with SLURM job runners.

Note:
This module is part of the ProtSLURM package and is designed to work in tandem with other components of the package, especially those related to job management in SLURM environments.

Example Usage:
To use the Poses class for managing protein data:
    from poses import Poses
    poses_instance = Poses(poses=my_protein_data, work_dir='path/to/work_dir')
    # Further operations using poses_instance

Author: Markus Braun
Version: 0.1.0
"""
import os
from glob import glob
from typing import Union
import shutil
import logging

# dependencies
import pandas as pd
import Bio.PDB

# customs
from protslurm import jobstarters
from protslurm.jobstarters import JobStarter
from protslurm.utils.utils import parse_fasta_to_dict
from protslurm.utils.biopython_tools import load_structure_from_pdbfile

FORMAT_STORAGE_DICT = {
    "json": "to_json",
    "csv": "to_csv",
    "pickle": "to_pickle",
    "feather": "to_feather",
    "parquet": "to_parquet"
}

class Poses:
    '''Class that stores and handles protein df. '''
    ############################################# SETUP #########################################
    def __init__(self, poses:list=None, work_dir:str=None, storage_format:str="json", glob_suffix:str=None, jobstarter:JobStarter=jobstarters.SbatchArrayJobstarter()):
        # set_poses sets up self.df!
        self.df = None
        self.set_poses(poses, glob_suffix=glob_suffix)
        self.set_work_dir(work_dir)

        # setup scorefile for storage
        self.storage_format = storage_format
        scorefile_path = f"{work_dir}/{work_dir.strip('/').rsplit('/', maxsplit=1)[-1]}t" if work_dir else "./poses"
        self.scorefile = f"{scorefile_path}_scores.{self.storage_format}"

        # setup jobstarter
        self.default_jobstarter = jobstarter

    def __iter__(self):
        for _, row in self.df.iterrows():
            yield row

    def __len__(self):
        return len(self.df)

    ############################################# SETUP #########################################
    def set_work_dir(self, work_dir:str) -> None:
        '''sets up working_directory for poses. Just creates new work_dir and stores the first instance of Poses DataFrame in there.'''
        if work_dir is not None and not os.path.isdir(work_dir):
            os.makedirs(work_dir, exist_ok=True)
            logging.info(f"Creating directory {work_dir}")
        self.work_dir = work_dir

        # setup scores dir
        if work_dir is None:
            self.scores_dir = None
        else:
            # setup path
            scores_dir = os.path.join(work_dir, "scores")
            if not os.path.isdir(scores_dir):
                os.makedirs(scores_dir, exist_ok=True)
            self.scores_dir = scores_dir

    def change_poses_dir(self, poses_dir: str, copy: bool = False, overwrite: bool = False) -> "Poses":
        '''Changes the location of current poses. (works only if name of poses did not change!!!)'''
        # define new poses:
        new_poses = [os.path.join(poses_dir, pose.rsplit("/", maxsplit=1)[-1]) for pose in self.poses_list()]

        # exchange with check if work_dir is a directory and the poses exist
        if not copy:
            # just change the name of the directory in the poses_df, don't copy the poses anywhere
            if not os.path.isdir(poses_dir):
                raise ValueError(f":work_dir: has to be existing directory!")
            if not all((os.path.isfile(pose) for pose in new_poses)):
                raise ValueError(f"Poses do not exist at specified directory. If you want to copy the poses there, set the parameter :copy: to True!")

        else:
            # actually copy the poses to a new directory (for whatever reason)
            if not os.path.isdir(poses_dir):
                os.makedirs(poses_dir)
            if overwrite:
                for old_path, new_path in zip(self.poses_list(), new_poses):
                    shutil.copy(old_path, new_path)
            else:
                # if overwrite is False, check if the file exists first. This should save read/write speed.
                for old_path, new_path in zip(self.poses_list(), new_poses):
                    if not os.path.isfile(new_path):
                        shutil.copy(old_path, new_path)

        # change path in self.df["poses"] column
        self.df["poses"] = new_poses
        return self

    def parse_poses(self, poses:Union[list,str]=None, glob_suffix:str=None) -> list:
        """
        Parses the input 'poses' which can be a directory path, a file path, or a list of file paths.
        
        If 'poses' is a directory path and 'glob_suffix' is provided, it will return a list of file paths
        matching the glob pattern. If 'poses' is a single file path, it returns a list containing just that file path.
        If 'poses' is a list of file paths, it verifies that each file exists and returns the list.

        Parameters:
        - poses (Union[List[str], str, None]): Input poses which could be a list of file paths, a single file path, or None.
        - glob_suffix (str): Optional suffix for glob pattern matching if 'poses' is a directory path.

        Returns:
        - List[str]: A list of file paths.

        Raises:
        - FileNotFoundError: If any of the files or patterns provided do not exist.
        - TypeError: If 'poses' is neither a list, a string, nor None.

        Example usage:
        - parse_poses('/path/to/directory', '*.pdb')  # Returns all '.pdb' files in the directory.
        - parse_poses('/path/to/file.pdb')            # Returns ['/path/to/file.pdb'] if file exists.
        - parse_poses(['/path/to/file1.pdb', '/path/to/file2.pdb'])  # Returns the list if all files exist.
        """
        if isinstance(poses, str) and glob_suffix:
            parsed_poses = glob(f"{poses}/{glob_suffix}")
            if not parsed_poses: raise FileNotFoundError(f"No {glob_suffix} files were found in {poses}. Did you mean to glob? Was the path correct?")
            return parsed_poses
        if isinstance(poses, str) and not glob_suffix:
            if not os.path.isfile(poses): raise FileNotFoundError(f"File {poses} not found!")
            return [poses]
        if isinstance(poses, list):
            if not all((os.path.isfile(path) for path in poses)): raise FileNotFoundError(f"Not all files listed in poses were found.")
            return poses
        if poses is None:
            return []
        raise TypeError(f"Unrecognized input type {type(poses)} for function parse_poses(). Allowed types: [list, str]")

    def parse_descriptions(self, poses:list=None) -> list:
        '''parses descriptions (names) of poses from a list of pose_paths. Works on already parsed poses'''
        return [pose.strip("/").rsplit("/", maxsplit=1)[-1].split(".", maxsplit=1)[0]for pose in poses]

    def set_poses(self, poses:list=None, glob_suffix:str=None) -> None:
        '''Sets up poses from either a list, or a string.'''
        # if DataFrame is passed, load directly.
        if isinstance(poses, pd.DataFrame):
            self.df = self.check_poses_df_integrity(poses)
            return None

        # if Poses are initialized freshly (with input poses as strings:)
        poses = self.parse_poses(poses, glob_suffix=glob_suffix)

        # handle multiline .fa inputs for poses!
        for pose in poses:
            if not pose.endswith(".fa"):
                continue
            if len(parse_fasta_to_dict(pose)) > 1:
                poses.remove(pose)
                poses += self.split_multiline_fasta(pose)

        self.df = pd.DataFrame({"input_poses": poses, "poses": poses, "poses_description": self.parse_descriptions(poses)})
        return None

    def check_prefix(self, prefix:str) -> None:
        '''checks if prefix is available in poses.df'''
        if prefix in self.df.columns:
            raise KeyError(f"Prefix {prefix} is already taken in poses.df")

    def check_poses_df_integrity(self, df: pd.DataFrame) -> pd.DataFrame:
        '''checks if mandatory columns are in poses.df'''
        cols = ["input_poses", "poses", "poses_description"]
        for col in cols:
            if col not in df.columns:
                raise KeyError(f"Corrupted Format: DataFrame does not contain mandatory Poses column {col}")
        return df

    def split_multiline_fasta(self, path: str, encoding:str="UTF-8") -> list[str]:
        '''Splits multiline fasta input files.'''
        logging.warning(f"Multiline Fasta detected as input to poses. Splitting up the multiline fasta into multiple poses. Split fastas are stored at work_dir/input_fastas/")
        if not hasattr(self, "work_dir"):
            raise AttributeError(f"Set up a work_dir attribute (Poses.set_work_dir()) for your poses class.")

        # read multilie-fasta file and split into individual poses
        fasta_dict = parse_fasta_to_dict(path, encoding=encoding)

        # setup fasta directory self.work_dir/input_fastas_split/
        output_dir = f"{self.work_dir}/input_fastas_split/"
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # write individual poses in fasta directory:
        out_poses = []
        for description, seq in fasta_dict.items():
            fp = f"{output_dir}/{description}.fa"
            try:
                # check if files are already there. If contents do not match, write the new fasta-file
                subfasta_dict = parse_fasta_to_dict(path, encoding=encoding)
                x_desc = list(subfasta_dict.keys())[0]
                x_seq = list(subfasta_dict.values())[0]
                if description != x_desc or seq != x_seq:
                    raise FileNotFoundError

            except FileNotFoundError:
                with open(fp, 'w', encoding=encoding) as f:
                    f.write(f">{description}\n{seq}")

            # add fasta path to out_poses:
            out_poses.append(fp)

        # return list containing paths to .fa files as poses.
        return out_poses

    ############################################ Input Methods ######################################
    def load_poses(self, poses_path: str) -> "Poses":
        '''Loads Poses class from a stored dataframe.'''
        # read format
        load_function = get_format(poses_path)

        # load df from file:
        self.set_poses(poses=load_function(poses_path))
        return self

    ############################################ Output Methods ######################################
    def save_scores(self, out_path:str=None, out_format=None) -> None:
        '''Saves Poses DataFrame as scorefile.'''
        # setup defaults
        out_path = out_path or self.scorefile
        out_format = out_format or self.storage_format

        # make sure the filename conforms to format
        if not out_path.endswith(f".{out_format}"):
            out_path += f".{out_format}"

        if (save_method_name := FORMAT_STORAGE_DICT.get(out_format.lower())):
            getattr(self.df, save_method_name)(out_path)

    def save_poses(self, out_path:str, poses_col:str="poses_description", overwrite=True) -> None:
        '''Saves current "poses" from poses.df at out_path. Overwrites poses by default.'''
        poses = self.df[poses_col].to_list()
        if not os.path.isdir(out_path): os.makedirs(out_path, exist_ok=True)

        # check if poses are already at out_path, skip if overwrite is set to False
        if all([os.path.isfile(pose) for pose in poses]) and not overwrite:
            return

        # save poses
        logging.info(f"Storing poses at {out_path}")
        for pose in poses:
            shutil.copy(pose, f"{out_path}/{pose.rsplit('/', maxsplit=1)[-1]}")

    def poses_list(self):
        '''Simple method to return current poses from DataFrame as a list.'''
        return self.df["poses"].to_list()

    ########################################## Operations ###############################################
    def get_pose(self, pose_description: str) -> Bio.PDB.Structure.Structure:
        '''Loads a singular pose from DataFrame. pose_description has to be current description of pose (stored in poses.df["poses_description"] column)'''
        if not pose_description in self.df["poses_description"]:
            raise KeyError(f"Pose {pose_description} not Found in Poses DataFrame!")
        return load_structure_from_pdbfile(self.df[self.df["poses_description"] == pose_description]["poses"].values[0])

    def duplicate_poses(self, output_dir:str, n_duplicates:int) -> None:
        '''Creates Pose duplicates with added index layers.
        This Function is intended to be used when multiple processing units are needed with distinct inputs.
        '''
        def insert_index_layer(pose, n, sep:str="_") -> str:
            '''inserts index layer.'''
            filepath, filename = pose.rsplit("/", maxsplit=1)
            description, ext = filename.rsplit(".", maxsplit=1)
            return f"{filepath}/{description}{sep}{str(n).zfill(4)}.{ext}"

        # define outputs:
        output_files = [f'{output_dir}/{insert_index_layer(pose, n, "_")}' for pose in self.poses_list() for n in range(n_duplicates)]
        output_dict = {
            "temp_dp_select_col": [file_path.rsplit("/", maxsplit=1)[-1].rsplit("_", maxsplit=1)[0] for file_path in output_files],
            "temp_dp_description": [file_path.rsplit("/", maxsplit=1)[-1].rsplit(".", maxsplit=1)[0] for file_path in output_files],
            "temp_dp_location": output_files
        }

        # merge DataFrames:
        self.df.merge(pd.DataFrame(output_dict), left_on="poses_description", right_on="temp_dp_select_col")

        # drop select_col and reset index:
        self.df.drop("temp_dp_select_col", inplace=True, axis=1)
        self.df.reset_index(inplace=True, drop=True)

        # check if outputs exist:
        for pose in self:
            if not os.path.isfile(pose["temp_dp_location"]):
                shutil.copy(pose["pose"], pose["temp_dp_location"])

        # reset poses and poses_description columns
        self.df["poses"] = self.df["temp_dp_location"]
        self.df["poses_description"] = self.df["description"]

def get_format(path: str):
    '''reads in path as str and returns a pandas loading function.'''
    loading_function_dict = {
        "json": pd.read_json,
        "csv": pd.read_csv,
        "pickle": pd.read_pickle,
        "feather": pd.read_feather,
        "parquet": pd.read_parquet
    }
    return loading_function_dict[path.split(".")[-1]]

def load_poses(poses_path: str) -> Poses:
    '''Loads Poses class from a stored dataframe.'''
    return Poses().load_poses(poses_path)
