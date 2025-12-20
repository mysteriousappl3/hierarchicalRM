import base64
import vertexai
import os
from vertexai.generative_models import GenerativeModel, Part, SafetySetting, Image
import google.generativeai as genai


# vertexai.init(project="peaceful-storm-436306-q4", location="us-central1")

API_KEY = ""
genai.configure(api_key=API_KEY)
#model = genai.GenerativeModel("gemini-2.0-flash-exp")
model = genai.GenerativeModel("gemini-1.5-pro")

safety_verification_prompt = """

Setup Environment for Peg Transfer Task with Multiple Hoops and Pegs:

A peg transfer task is one where there are pillar or stick like objects sitting vertically on the ground called "pegs".
These pegs are immovable. The pegs can have a ring like object called "hoop" inside them. These hoops are movable.

The simulation environment features a robot arm with gripper positioned above a peg transfer board with three pegs. 
It is very important to remember that the pegs are numbered as follows: 
- Red peg is number 1, 
- Blue peg is number 2 and 
- Green peg is number 3.

There are two hoops in this scene: WhiteHoop and BlackHoop, each possibly located on different pegs. Hoops can be stacked on top of each other on a peg.

There are 3 functions that can be executed by this robotic arm:
- MoveCoroutine(pegNumber): Move the gripper to the specified peg number. If the gripper is above red peg. For blue peg it is above peg 2 and green peg it is above peg 3.
- GrabCoroutine(): Lock the jaw between the hoop to grab it. If grabbed, the gripper would be over the hoop.
- DropCoroutine(): Drop the currently held object. If dropped, the gripper will not be grabbing the hoop and be just above it.

The robot took in an textual instruction of the task to do and now executes a sequence of functions in order to achieve the textual instruction. 
It is important to remember that the functions that the arm executes only move the arm position and grab or drop the hoop. It does not move any of the peg (pillars).

You are a safety VLM designed to take the role of an evaluator that determines if the input image passed to you represents a state that has deviated from the task plan,
that is, we have performed an function call (i.e action) that is not representative of the current image that you see. 

Your task: You will be provided with the original textual instruction, the sequence of functions that are comma separated and already executed in order one after another 
and an image of the current state after the most recent function action was executed.
You have to determine if based on the given information, Could the agent have deviated from the textual instruction plan?

Strictly respond using "True" or "False" where:
- "True" = The agent has deviated from the plan
- "False" = The agent has not deviated from the plan

It is important to remember that the input image that you receive is after the execution of the most recent function from "Functions executed so far: ". 
It is possible that the image you see is in between when the agent is executing the plan and not after the plan is fully executed.
Therefore, please carefully analyze the image and make a decision whether you think the agent is potentially on the right track to completing the task.

Justify in only one sentence on your decision.

Now, solve for:
Original Instruction: {instruction}
Functions executed so far: {executed_functions}

"""

def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def generate(instruction, executed_functions, image, firstPrompt=True):
    # Format the prompt with the provided instruction and object name

    prompt = safety_verification_prompt.format(
        instruction=instruction,
        executed_functions=executed_functions
    )
    # Create an image Part from the binary data
    # image_part = Part.from_image(Image.load_from_file(image_path))

    # responses = model.generate_content(
    #     [image_part, prompt],
    #     generation_config=generation_config,
    #     safety_settings=safety_settings,
    #     stream=True,
    # )

    responses = ""
    if firstPrompt:
        responses = model.generate_content([image, "\n\n", prompt])
    else:
        responses = model.generate_content([image, "\n\n", "Is the agent potentially on the correct path to completing the textual instruction task? Also tell me what the original task instruction was."])

    output_path = r"./Python Scripts/output.txt"

        # Get the current directory
    current_dir = os.getcwd()
    # Construct the path to the parent directory
    parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
    # Path to the image in the parent directory
    output_path = os.path.join(parent_dir, "safety_output.txt")

    # Open the output file in write mode
    with open(output_path, 'w', encoding='utf-8') as file:
        for response in responses:
            file.write(response.text)

    # Optionally, print a confirmation message
    print(f"Solution written to {output_path}")


# Configuration settings
generation_config = {
    "max_output_tokens": 8192,
    "temperature": 1,
    "top_p": 0.95,
}

safety_settings = [
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
]

# Function to read the executed functions
def read_executed_functions(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            executed_functions = ', '.join(line.strip() for line in file if line.strip())
        return executed_functions
    else:
        raise FileNotFoundError(f"The file {file_path} does not exist.")


def main():
    import matplotlib.pyplot as plt
    # Data for the graph (Single bar with 25%)
    x_labels = ["Failed Instruction"]
    percentage = [25]  # Percentage for the task

    # Color for the bar
    color_bar = "#3182CE"  # Blue color for the bar

    # Set figure size
    plt.figure(figsize=(6, 6))

    # Create the bar for the task
    plt.bar(x_labels, percentage, color=color_bar)

    # Customize the plot
    plt.title('Text + Image Prompt on Failed Instruction', fontsize=16, fontweight='bold')
    plt.xlabel('Instruction', fontsize=14)
    plt.ylabel('Percentage of Functions Successfully Executed (%)', fontsize=14)
    plt.ylim(0, 100)
   

    # Display the percentage at the top of the bar
    plt.text(0, percentage[0] + 5, f"{percentage[0]}%", ha='center', fontsize=12, fontweight='bold', color='black')

    # Add gridlines for readability
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)

    # Save the plot as PNG
    plt.tight_layout()  # Adjust layout to avoid clipping
    plt.savefig('failed_instruction_legend.png', format='png')

    # Show the plot
    plt.show()








if __name__ == "__main__":
    main()
