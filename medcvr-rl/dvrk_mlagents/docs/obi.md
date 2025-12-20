# Obi Solver

We use Obi to implement rope, cloth, and soft body physics. Obi is a paid asset, and is bought through the Unity Asset Store. Below are some improtant notes about Obi, and using Obi in scenes. Read this thorougly before working with Obi, it is the summation of the current knowledge and tips we have on this Asset.

- Do not distribute Obi, it is a paid Asset. It gets cloned into our Assets folder, and so can be distributed internally, but this is okay as we have paid for Seats for this Asset. Any scenes that have Obi Assets *NEED* to be removed prior to public release.

- There are sample scenes inside the Obi folder that show how the Assets can be used. There is also a website with API documentation as well as Forums with commonly asked questions

- Obi works for URP, but the Assets needs to be converted. Go to `Windows->Rendering->Render Pipeline Converter`, use `Built-in to URP`, and initialize all the converters available, and Convert all. Some may not convert, and some ml-agents specific materials will also become converted (if you had not converted them before), but overall this works and all the important materials get converted.

### Tips for Obi inside scenes

- Obi can be duplicated across the environment prefabs for ML-Agents, but to make it efficient to use, the `Obi Fixed Updater` is kept seperately from the `Solver` and `Actor` (Rope/Cloth are `Actors`). Multiple solver can exist, but only one `Updater` script should be used Globally. Each `Solver` must then be linked to this global updater under it's public `Solvers` interface.

- The `actor` (e.g. Rope) needs a local solver. The solver indexes the particles of the actor. A rope has a number of particles based on length and thickness. We can get the position and velocities of these particles, which is useful for vector-based observation logic, and goal-checking. Although the official API suggests that using the `solver` as a reference, you can get access to all attached particles, this did not work in practice. it was easier to access directly the `rope` and use its own indexing and functions to get the correct particle information.