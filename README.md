# HierarchicalRM Project

A Unity-based surgical peg transfer task driven by HierarchicalRM pipeline. The system breaks a natural-language instruction into a hierarchy of robot actions and executes them using a simulated dvrk robot arm.

---

## Navigating the Repository

Most of the relevant code lives inside the Unity project. Please navigate to:

```
src/unity_project/Assets/Tasks/PegTransferTask/
```

---

## PegTransferTask

### Folder Structure

```
PegTransferTask/
├── Prefabs/          # Scene prefabs for different ring counts
├── Scenes/           # Unity scenes for each configuration
├── Scripts/          # All C# scripts for the task
└── Task_Images/      # Screenshots captured during task execution
```

### Prefabs

Three prefabs are available depending on how many rings your task involves:

| Prefab | Scene |
|---|---|
| `Prefabs/3Rings_Scene.prefab` | `Scenes/3Rings.unity` |
| `Prefabs/4Rings_Scene.prefab` | `Scenes/4Rings.unity` |
| `Prefabs/5Rings_Scene.prefab` | `Scenes/5Rings.unity` |

Open the matching scene for your desired ring count before running.

### Scripts Overview

| Script | Role |
|---|---|
| `Main.cs` | Central controller — holds the OpenAI API key/URLs, the `pegColorToNumMapping`, and orchestrates execution of hierarchical functions |
| `PipelineExecutor.cs` | Utility UI script — reads the task instruction from the input field and kicks off the full pipeline via `APIRunner()` |
| `DecisionBot.cs` | Top-level planner — takes the user instruction and produces a sequence of H2/H1 function calls broken into subtasks |
| `OuterBot.cs` | Performs subtask/task completion and decides whether replanning is needed |
| `InnerBot.cs` | Performs verification for state description and decision bot plan and provides relevant feedback for correction |
| `H1ActionGenerator.cs` | Generates H1-level functions (single state changes, e.g. move one ring) from H0 primitives |
| `H2ActionGenerator.cs` | Generates H2-level functions (multi-step compositions of H1 functions) |
| `SceneDescriptor.cs` | Captures a screenshot and calls the VLM to produce a structured JSON scene description |
| `StateDescriptor.cs` | Uses the scene description and user instruction to produce goal and constraint spatial relation dictionaries |
| `LowLevelMotor.cs` | Executes physical robot movements — move to peg, grab ring, drop ring |

### API Endpoints

Both API key and URLs are configured in `Scripts/Main.cs`:

```csharp
private string openAIKey = "...";
private const string openAIUrl          = "https://api.openai.com/v1/chat/completions";
private const string openAIReasoningURL = "https://api.openai.com/v1/responses";
```

Swap in your own key there before running.

---

### How to Run

1. Open the Unity scene that matches your desired ring count (`3Rings`, `4Rings`, or `5Rings`).
2. Configure the **PegConfigs** on the `Agent` game object found under `Src` parent object in scene.
3. Enter your task instruction in the on-screen input field.
4. Press **Execute Pipeline** button — `PipelineExecutor` triggers `APIRunner()`, which runs the HierarchicalRM pipeline to solve your task.

---

### Important Note: PegConfigs Mapping Before Running Pipeline

`Agent` game object exposes a `pegConfigs` list in the Inspector. Each entry is a `PegHoopConfig` that links a **peg GameObject** to the **rings currently sitting on it**.


#### Convention: bottom-to-top.
---

Rings are listed from the bottom of the peg upward:
- **Element 0** → the bottom-most ring on that peg (e.g. `RingOne`)
- **Element 1** → the ring directly above it (e.g. `RingTwo`)
- and so on up to the top

Repeat this for the subsequent pegs and their individual ordering of hoops within them.

Before hitting Play, drag the peg and ring GameObjects from the Scene into each `pegConfigs` entry so the list reflects the actual physical stacking order you want as your starting state. The planner reads this mapping to know where every ring is at the start, so it must match what is visible in the scene view.
