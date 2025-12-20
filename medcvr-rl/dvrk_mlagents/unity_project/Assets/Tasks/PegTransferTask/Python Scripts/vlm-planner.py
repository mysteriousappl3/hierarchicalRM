import base64
import vertexai
import os
from vertexai.generative_models import GenerativeModel, Part, SafetySetting, Image
import google.generativeai as genai


# vertexai.init(project="peaceful-storm-436306-q4", location="us-central1")

API_KEY = ""
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-1.5-pro")

prompt_template3 = """
Setup Environment for Peg Transfer Task with Multiple Hoops and Pegs:

Functions:
- MoveCoroutine(pegNumber): Move the end effector to the specified peg number.
- GrabCoroutine(): Pick up the currently targeted object in the current peg the end effector is presently at.
- DropCoroutine(): Drop the currently held object.

The simulation environment features a gripper positioned above a peg transfer board, where three pegs.
It is important to remember that the pegs are numbered as follows: 
- Red peg is number 1, 
- Blue peg is number 2 and 
- Green peg is number 3.

These pegs are arranged for the peg-transfer task. There are two hoops in this scene: WhiteHoop and BlackHoop, 
each possibly located on different pegs or starting areas. *"Hoops can be stacked on top of each other on a peg.**
 Key location references are available for precise navigation and control, including the current position of the
   end-effector, each hoop, and designated grab locations on each hoop.

Key Game Objects:
- Hoops:
  - WhiteHoop: Represents the White hoop in the environment.
  - BlackHoop: Represents the Black hoop in the environment.
- Tool Position:
  - tool_midpoint: Midpoint of the tool, representing the gripper's position in the scene.
- Pegs:
  - Peg1: peg with number 1.
  - Peg2: peg with number 2.
  - Peg3: peg with number 3.

Aim of the Task:
Design a high-level motion planning strategy to complete peg transfer tasks involving multiple hoops and pegs. 
This includes utilizing the precise interaction points to guide the gripper's movements, ensuring accurate and 
efficient peg manipulation in the simulated environment.

**Important Considerations:**
Hoops may be stacked on pegs. If the hoop you need to move is underneath other hoops, you need to first 
remove the hoops above it to access it When moving hoops that are temporarily relocated, remember to place 
them back to their original or desired positions after completing the task.If a hoop is already on the desired 
peg and accessible (i.e., not blocked by other hoops), you do not need to move it, as moving it would be redundant.

---

Example 1:

Instruction:
Place the WhiteHoop onto Peg1 and the BlackHoop onto Peg2.

Chain of Thought:
1.The end effector is currently at the tool_midpoint.
2.Determine where the WhiteHoop is currently located.
3.Move to the peg where WhiteHoop is located to pick it up.
4.Grab the WhiteHoop.
5.Move to Peg1.
6.Drop the WhiteHoop onto Peg1.
7.Determine where the BlackHoop is currently located.
8.Move to the peg where BlackHoop is located to pick it up.
9.Grab the BlackHoop.
10.Move to Peg2.
11.Drop the BlackHoop onto Peg2.

Solution:
MoveCoroutine(1)  
GrabCoroutine()
MoveCoroutine(1) 
DropCoroutine()
MoveCoroutine(2) 
GrabCoroutine()
MoveCoroutine(2)
DropCoroutine()


---

Example 2:

Initial State:
- WhiteHoop is on Peg1, with BlackHoop stacked above it.
- Peg2 is empty.
- Peg3 is empty.

Instruction:
Move WhiteHoop to Peg3.

Chain of Thought:
1.The end effector is currently at the tool_midpoint.
2.WhiteHoop is on Peg1 but is blocked by BlackHoop above it.
3.Need to move BlackHoop to access WhiteHoop.
4.Move to Peg1 to access BlackHoop.
5.Grab the BlackHoop from Peg1.
6.Move to Peg2 to temporarily place BlackHoop.
7.Drop the BlackHoop onto Peg2.
8.Now, WhiteHoop is accessible on Peg1.
9.Move to Peg1 to pick up WhiteHoop.
10.Grab the WhiteHoop from Peg1.
11.Move to Peg3.
12.Drop the WhiteHoop onto Peg3.
13.Optionally, move BlackHoop back to its original position if required.

Solution:
MoveCoroutine(1)
GrabCoroutine()
MoveCoroutine(2)
DropCoroutine()
MoveCoroutine(1)
GrabCoroutine()
MoveCoroutine(3)
DropCoroutine()

---

Example 3:

Initial State:
- BlackHoop is on Peg2, with WhiteHoop stacked above it.
- Peg1 is empty.
- Peg3 is empty.

Instruction:
Place WhiteHoop onto Peg3.

Chain of Thought:
1.The end effector is currently at the tool_midpoint.
2.WhiteHoop is on Peg2 and is above BlackHoop, so it is accessible.
3.Move to Peg2 to access WhiteHoop.
4.Grab the WhiteHoop from Peg2.
5.Move to Peg3.
6.Drop the WhiteHoop onto Peg3.

Solution:
MoveCoroutine(2) 
GrabCoroutine()  
MoveCoroutine(3) 
DropCoroutine()

---

Now, solve the following:
Instruction: {instruction}

Chain of Thought:
"""

def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def generate(instruction, input_image):
    # Format the prompt with the provided instruction and object name
    prompt = prompt_template3.format(
        instruction=instruction,
    )
    # Create an image Part from the binary data
    # image_part = Part.from_image(Image.load_from_file(image_path))

    # responses = model.generate_content(
    #     [image_part, prompt],
    #     generation_config=generation_config,
    #     safety_settings=safety_settings,
    #     stream=True,
    # )

    responses = model.generate_content([input_image, "\n\n", prompt])

    output_path = r"./Python Scripts/output.txt"

        # Get the current directory
    current_dir = os.getcwd()
    # Construct the path to the parent directory
    parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
    # Path to the image in the parent directory
    output_path = os.path.join(parent_dir, "plan.txt")

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


def main():
    # Get the current directory
    current_dir = os.getcwd()
    # Construct the path to the parent directory
    parent_dir = os.path.abspath(os.path.join(current_dir, "../Task_Images"))
    # Path to the image in the parent directory
    image_path = os.path.join(parent_dir, "Image_1.png")

    # Add image to gemini model
    image = genai.upload_file(image_path)



    # image_path = "../Image"  # Path to your local image file
    while True:
        print("\n--- Robotic Surgery Command Generator ---")
        instruction = input("Enter your instruction (or type 'exit' to quit): ")
        if instruction.lower() == 'exit':
            print("Exiting the program.")
            break
        generate(instruction, image)
        print("\n--- Command Generation Complete ---\n")
        break


if __name__ == "__main__":
    main()
