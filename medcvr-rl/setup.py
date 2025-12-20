from setuptools import setup
from mlagents.plugins import ML_AGENTS_TRAINER_TYPE

setup(
    name="medcvr_rl",
    version="0.0.1",
    install_requires=[
        "matplotlib",
        "numpy",
        "mlagents",
        "mlagents-envs",
    ],
    packages=['medcvr_rl'],
    entry_points={
        ML_AGENTS_TRAINER_TYPE: [
            "cx_ppo=medcvr_rl.mlagents.cx_ppo:get_type_and_setting",
        ]
    },
)