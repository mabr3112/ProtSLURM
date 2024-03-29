'''Module to handle Rosetta Scripts within ProtSLURM'''
# general imports
import os
import time
import logging
from glob import glob
import shutil

# dependencies
import pandas as pd

# custom
import protslurm.config
import protslurm.jobstarters
from protslurm.poses import Poses
import protslurm.tools
from protslurm.runners import Runner, RunnerOutput
from protslurm.jobstarters import JobStarter


class RosettaScripts(Runner):
    '''Class to run Rosetta Scripts and collect its outputs into a DataFrame'''
    def __init__(self, script_path:str=protslurm.config.ROSETTA_SCRIPTS_PATH, jobstarter:JobStarter=None) -> None:
        '''jobstarter_options are set automatically, but can also be manually set. Manual setting is not recommended.'''
        if not script_path: raise ValueError(f"No path is set for {self}. Set the path in the config.py file under ROSETTA_SCRIPTS_PATH.")
        self.script_path = script_path
        self.name = "rosetta_scripts.py"
        self.index_layers = 1
        self.jobstarter = jobstarter

    def __str__(self):
        return "rosettascripts.py"

    def run(self, poses:Poses, prefix:str, xml_path:str, jobstarter:JobStarter=None, nstruct:int=1, params_path:str=None, options:str=None, pose_options:list[str]=None, overwrite:bool=False) -> RunnerOutput: # pylint: disable=W0237
        '''Runs rosettascripts.py'''
        # setup runner
        work_dir, jobstarter = self.generic_run_setup(
            poses=poses,
            prefix=prefix,
            jobstarters=[jobstarter, self.jobstarter, poses.default_jobstarter]
        )

        # Look for output-file in pdb-dir. If output is present and correct, then skip RosettaScripts.
        rosettascore_path = os.path.join(work_dir, 'rosettascripts_scores.sc')
        scorefilepath = os.path.join(work_dir, "rosettascripts_scores.json")
        if not overwrite and os.path.isfile(scorefilepath):
            return RunnerOutput(poses=poses, results=pd.read_json(scorefilepath), prefix=prefix, index_layers=self.index_layers).return_poses()
        elif overwrite and os.path.isdir(work_dir):
            if os.path.isfile(scorefilepath):
                os.remove(scorefilepath)
            if os.path.isfile(rosettascore_path):
                os.remove(rosettascore_path)

        # parse_options and pose_options:
        pose_options = self.prep_pose_options(poses, pose_options)

        # write rosettascripts cmds:
        cmds = []
        for pose, pose_opts in zip(poses.df['poses'].to_list(), pose_options):
            for i in range(1, nstruct+1):
                cmds.append(self.write_cmd(pose, output_dir=work_dir, xml_path=xml_path, i=i, rosettascore_path=rosettascore_path, params_path=params_path, overwrite=overwrite, options=options, pose_options=pose_opts))

        # run
        jobstarter.start(
            cmds=cmds,
            jobname="rosettascripts",
            wait=True,
            output_path=f"{work_dir}/"
        )

        # collect scores and rename pdbs.
        time.sleep(10) # Rosetta does not have time to write the last score into the scorefile otherwise?

        # collect scores
        scores = self.collect_scores(work_dir=work_dir, rosettascore_path=rosettascore_path, scorefilepath=scorefilepath)

        return RunnerOutput(poses=poses, results=scores, prefix=prefix, index_layers=self.index_layers).return_poses()

    def create_pose_options(self, df:pd.DataFrame, pose_options:list[str]=None) -> list:
        '''Checks if pose_options are of the same length as poses, if pose_options are provided, '''

        def check_if_column_in_poses_df(df:pd.DataFrame, column:str):
            if not column in [col for col in df.columns]: raise ValueError(f"Could not find {column} in poses dataframe! Are you sure you provided the right column name?")
            return

        poses = df['poses'].to_list()

        if isinstance(pose_options, str):
            check_if_column_in_poses_df(df, pose_options)
            pose_options = df[pose_options].to_list()
        # safety check (pose_options must have the same length as poses)
        if pose_options is None:
            # make sure an empty list is passed as pose_options!
            pose_options = ["" for x in poses]

        if len(poses) != len(pose_options):
            raise ValueError(f"Arguments <poses> and <pose_options> for RosettaScripts must be of the same length. There might be an error with your pose_options argument!\nlen(poses) = {poses}\nlen(pose_options) = {len(pose_options)}")
        return pose_options

    def write_cmd(self, pose_path:str, output_dir:str, xml_path:str, i:int, rosettascore_path:str, params_path:str=None, overwrite:bool=False, options:str=None, pose_options:str=None):
        '''Writes Command to run rosettascripts.py'''

        # parse options
        opts, flags = protslurm.runners.parse_generic_options(options, pose_options)

        # check for xml_path:
        opts = " ".join([f"-{key} {value}" for key, value in opts.items()])
        flags = " -".join(flags)
        run_string = f"{self.script_path} -parser:protocol {xml_path} -out:path:all {output_dir} -in:file:s {pose_path} -out:prefix r{str(i).zfill(4)}_ -out:file:scorefile {rosettascore_path} {opts} {flags}"
        if params_path:
            run_string = run_string + f" -extra_res_fa {params_path}"
        if overwrite:
            run_string = run_string + f" -overwrite"
        return run_string


    def collect_scores(self, work_dir:str, rosettascore_path:str, scorefilepath:str) -> pd.DataFrame:
        '''
        Collects scores and reindexes .pdb files. Stores scores as .json file.
        '''
        def clean_rosetta_scorefile(path_to_file: str, out_path: str) -> str:
            '''cleans a faulty rosetta scorefile'''

            # read in file line-by-line:
            with open(path_to_file, 'r', encoding="UTF-8") as f:
                scores = [line.split() for line in list(f.readlines()[1:])]

            # if any line has a different number of scores than the header (columns), that line will be removed.
            scores_cleaned = [line for line in scores if len(line) == len(scores[0])]
            logging.warning(f"WARNING: {len(scores) - len(scores_cleaned)} scores were removed from Rosetta scorefile at {path_to_file}")

            # write cleaned scores to file:
            with open(out_path, 'w', encoding="UTF-8") as f:
                f.write("\n".join([",".join(line) for line in scores_cleaned]))
            return out_path

        try:
            scores = pd.read_csv(rosettascore_path, delim_whitespace=True, header=[1], na_filter=True)
        except pd.errors.ParserError:
            logging.warning(f"WARNING: Error reading Rosetta Scorefile. Removing faulty scorelines. This means that a few calculations will be lost.")
            scores = pd.read_csv(clean_rosetta_scorefile(rosettascore_path, os.path.join(work_dir, "clean_rosetta_scores.sc")))

        # remove rows from df that do not contain scores and remove "description" duplicates, because that's what happens in Rosetta...
        scores = scores[scores["SCORE:"] == "SCORE:"]
        scores = scores.drop_duplicates(subset="description")

        # create reindexed names of relaxed pdb-files: [r0003_pose_unrelaxed_0001.pdb -> pose_unrelaxed_0003.pdb]
        scores.rename(columns={"description": "raw_description"}, inplace=True)
        scores.loc[:, "description"] = scores["raw_description"].str.split("_").str[1:-1].str.join("_") + "_" + scores["raw_description"].str.split("_").str[0].str.replace("r", "")

        # wait for all Rosetta output files to appear in the output directory (for some reason, they are sometimes not there after the runs completed.)
        while len((fl := glob(f"{work_dir}/r*.pdb"))) < len(scores):
            time.sleep(1)

        # rename .pdb files in work_dir to the reindexed names.
        names_dict = scores[["raw_description", "description"]].to_dict()
        print(f"Renaming and reindexing {len(scores)} Rosetta output .pdb files")
        for oldname, newname in zip(names_dict["raw_description"].values(), names_dict["description"].values()):
            shutil.move(f"{work_dir}/{oldname}.pdb", (nf := f"{work_dir}/{newname}.pdb"))
            if not os.path.isfile(nf):
                print(f"WARNING: Could not rename file {oldname} to {nf}\n Retrying renaming.")
                shutil.move(f"{work_dir}/{oldname}.pdb", (nf := f"{work_dir}/{newname}.pdb"))

        # Collect information of path to .pdb files into dataframe under "location" column
        scores.loc[:, "location"] = work_dir + "/" + scores["description"] + ".pdb"

        # safetycheck rename all remaining files with r*.pdb into proper filename:
        if (remaining_r_pdbfiles := glob(f"{work_dir}/r*.pdb")):
            for pdb_path in remaining_r_pdbfiles:
                pdb_path = pdb_path.split("/")[-1]
                idx = pdb_path.split("_")[0].replace("r", "")
                new_name = "_".join(pdb_path.split("_")[1:-1]).replace(".pdb", "") + "_" + idx + ".pdb"
                shutil.move(f"{work_dir}/{pdb_path}", f"{work_dir}/{new_name}")

        # reset index and write scores to file
        scores.reset_index(drop="True", inplace=True)
        scores.to_json(scorefilepath)

        return scores
