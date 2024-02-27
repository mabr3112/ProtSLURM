'''Module to handle RFdiffusion within ProtSLURM'''
# general imports
import os
import logging
from glob import glob
import re
import numpy as np

# dependencies
import pandas as pd

# custom
import protslurm.config
import protslurm.jobstarters
import protslurm.runners
from .runners import Runner
from .runners import RunnerOutput


class RFdiffusion(Runner):
    '''Class to run RFdiffusion and collect its outputs into a DataFrame'''
    def __init__(self, script_path:str=protslurm.config.RFDIFFUSION_SCRIPT_PATH, python_path:str=protslurm.config.RFDIFFUSION_PYTHON_PATH, jobstarter_options:str=None) -> None:
        '''jobstarter_options are set automatically, but can also be manually set. Manual setting is not recommended.'''
        if not script_path: raise ValueError(f"No path is set for {self}. Set the path in the config.py file under RFDIFFUSION_SCRIPT_PATH.")
        if not python_path: raise ValueError(f"No python path is set for {self}. Set the path in the config.py file under RFDIFFUSION_PYTHON_PATH.")
        self.script_path = script_path
        self.python_path = python_path
        self.name = "rfdiffusion.py"
        self.index_layers = 1
        self.jobstarter_options = jobstarter_options

    def __str__(self):
        return "rfdiffusion.py"

    def run(self, poses:protslurm.poses.Poses, output_dir:str, prefix:str, num_diffusions:int=1, options:str=None, pose_options:list or str=None, overwrite:bool=False, jobstarter:protslurm.jobstarters.JobStarter=None) -> RunnerOutput:
        '''Runs rfdiffusion.py on acluster'''

        # setup directory
        work_dir = os.path.abspath(output_dir)
        if not os.path.isdir(work_dir): os.makedirs(work_dir, exist_ok=True)
        pdb_dir = os.path.join(work_dir, "output_pdbs")
        if not os.path.isdir(pdb_dir): os.makedirs(pdb_dir, exist_ok=True)

        # Look for output-file in pdb-dir. If output is present and correct, then skip diffusion step.
        scorefile="rfdiffusion_scores.json"
        scorefilepath = os.path.join(work_dir, scorefile)

        if overwrite is False and os.path.isfile(scorefilepath):
            return RunnerOutput(poses=poses, results=pd.read_json(scorefilepath), prefix=prefix, index_layers=self.index_layers).return_poses()
        elif overwrite is True or not os.path.isfile(scorefilepath):
            if os.path.isfile(scorefilepath): os.remove(scorefilepath)
            for pdb in glob(f"{pdb_dir}/*pdb"):
                if os.path.isfile(trb := pdb.replace(".pdb", ".trb")):
                    os.remove(trb)
                    os.remove(pdb)


        # parse options and pose_options:
        pose_options = self.create_pose_options(poses.df, pose_options)

        # write rfdiffusion cmds
        cmds = [self.write_cmd(pose, options, pose_opts, output_dir=pdb_dir, num_diffusions=num_diffusions) for pose, pose_opts in zip(poses.df["poses"].to_list(), pose_options)]
        
        # run diffusion
        jobstarter = jobstarter or poses.default_jobstarter
        jobstarter_options = self.jobstarter_options or f"--gpus-per-node 1 -c1 -e {work_dir}/rfdiffusion_err.log -o {work_dir}/rfdiffusion_out.log"
        jobstarter.start(cmds=cmds,
                         options=jobstarter_options,
                         jobname="rfdiffusion",
                         wait=True,
                         output_path=f"{work_dir}/"
        )

        scores = self.collect_scores(work_dir=work_dir, scorefile=scorefilepath, rename_pdbs=True)
        
        return RunnerOutput(poses=poses, results=scores, prefix=prefix, index_layers=self.index_layers).return_poses()

    def create_pose_options(self, df:pd.DataFrame, pose_options:list or str=None) -> list:
        '''Checks if pose_options are of the same length as poses, if pose_options are provided, '''

        def check_if_column_in_poses_df(df:pd.DataFrame, column:str):
            if not column in [col for col in df.columns]: raise ValueError(f"Could not find {column} in poses dataframe! Are you sure you provided the right column name?")
            return

        poses = df['poses'].to_list()


        if isinstance(pose_options, str):
            check_if_column_in_poses_df(df, pose_options)
            pose_options = df[pose_options].to_list()
        if pose_options is None:
            # make sure an empty list is passed as pose_options!
            pose_options = ["" for x in poses]

        if len(poses) != len(pose_options):
            raise ValueError(f"Arguments <poses> and <pose_options> for RFdiffusion must be of the same length. There might be an error with your pose_options argument!\nlen(poses) = {poses}\nlen(pose_options) = {len(pose_options)}")
        
        return pose_options
    

    def write_cmd(self, pose: str, options: str, pose_opts: str, output_dir: str, num_diffusions: int=1) -> str:
        '''AAA'''

        def parse_rfdiffusion_opts(options: str, pose_options: str) -> dict:
            '''AAA'''
            def re_split_rfdiffusion_opts(command) -> list:
                return re.split(r"\s+(?=(?:[^']*'[^']*')*[^']*$)", command)
            
            splitstr = [x for x in re_split_rfdiffusion_opts(options) + re_split_rfdiffusion_opts(pose_options) if x]# adding pose_opts after options makes sure that pose_opts overwrites options!
            return {x.split("=")[0]: "=".join(x.split("=")[1:]) for x in splitstr}
        
        # parse description:
        desc = os.path.splitext(os.path.basename(pose))[0]

        # parse options:
        start_opts = parse_rfdiffusion_opts(options, pose_opts)

        if not "inference.output_prefix" in start_opts: start_opts["inference.output_prefix"] = os.path.join(output_dir, desc)
        if not "inference.input_pdb" in start_opts: start_opts["inference.input_pdb"] = pose
        if not "inference.num_designs" in start_opts: start_opts["inference.num_designs"] = num_diffusions

        opts_str = " ".join([f"{k}={v}" for k, v in start_opts.items()])

        # return cmd
        return f"{self.python_path} {self.script_path} {opts_str}"


    def collect_scores(self, work_dir:str, scorefile:str, rename_pdbs:bool=True) -> pd.DataFrame:
        '''collects scores from RFdiffusion output'''

        def parse_diffusion_trbfile(path: str) -> pd.DataFrame:
            '''AAA'''
            # read trbfile:
            if path.endswith(".trb"): data_dict = np.load(path, allow_pickle=True)
            else: raise ValueError(f"only .trb-files can be passed into parse_inpainting_trbfile. <trbfile>: {path}")

            # calc mean_plddt:
            sd = dict()
            last_plddts = data_dict["plddt"][-1]
            sd["plddt"] = [sum(last_plddts) / len(last_plddts)]
            sd["perres_plddt"] = [last_plddts]

            # instantiate scoresdict and start collecting:
            scoreterms = ["con_hal_pdb_idx", "con_ref_pdb_idx", "sampled_mask"]
            for st in scoreterms:
                sd[st] = [data_dict[st]]

            # collect metadata
            sd["location"] = path.replace(".trb", ".pdb")
            sd["description"] = path.split("/")[-1].replace(".trb", "")
            sd["input_pdb"] = data_dict["config"]["inference"]["input_pdb"]

            return pd.DataFrame(sd)

        # collect scores from .trb-files into one pandas DataFrame:
        pdb_dir = os.path.join(work_dir, "output_pdbs")
        pl = glob(f"{pdb_dir}/*.pdb")
        if not pl: raise FileNotFoundError(f"No .pdb files were found in the diffusion output direcotry {pdb_dir}. RFDiffusion might have crashed (check inpainting error-log), or the path might be wrong!")

        # collect rfdiffusion scores into a DataFrame:
        scores = []
        for pdb in pl:
            if os.path.isfile(trb := pdb.replace(".pdb", ".trb")):
                scores.append(parse_diffusion_trbfile(trb))
        scores = pd.concat(scores)

        # rename pdbs if option is set:
        if rename_pdbs is True:
            scores.loc[:, "new_description"] = ["_".join(desc.split("_")[:-1]) + "_" + str(int(desc.split("_")[-1]) + 1).zfill(4) for desc in scores["description"]]
            scores.loc[:, "new_loc"] = [loc.replace(old_desc, new_desc) for loc, old_desc, new_desc in zip(list(scores["location"]), list(scores["description"]), list(scores["new_description"]))]

            # rename all diffusion outputfiles according to new indeces:
            _ = [[os.rename(f, f.replace(old_desc, new_desc)) for f in glob(f"{pdb_dir}/{old_desc}.*")] for old_desc, new_desc in zip(list(scores["description"]), list(scores["new_description"]))]

            # Collect information of path to .pdb files into DataFrame under 'location' column
            scores = scores.drop(columns=["location"]).rename(columns={"new_loc": "location"})
            scores = scores.drop(columns=["description"]).rename(columns={"new_description": "description"})

        scores.reset_index(drop=True)

        logging.info(f"Saving scores of {self} at {scorefile}")
        scores.to_json(scorefile)

        return scores