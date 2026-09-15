"""Streamlit web application for the AoT+ Planning System."""
import streamlit as st
import numpy as np
import time
import os
import sys
from typing import Optional, List

# Add the parent directory to path to make imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now import the modules
from src.aot_plus.core import AoTPlus
from src.domains.blocksworld import BlocksWorldDomain
from src.domains.logistics import LogisticsDomain
from src.utils.config import Config
from src.models.llm_client import get_llm_client

# Page configuration
st.set_page_config(
    page_title="AoT+ Planning System",
    page_icon="🤖",
    layout="wide"
)

# Add custom CSS
st.markdown("""
<style>
    .block {
        display: inline-block;
        width: 50px;
        height: 50px;
        margin: 5px;
        border: 2px solid black;
        text-align: center;
        line-height: 50px;
        font-weight: bold;
    }
    .main-header {
        text-align: center;
        font-size: 2.5em;
        margin-bottom: 20px;
    }
    .subheader {
        font-size: 1.5em;
        margin-bottom: 10px;
    }
    .location-label {
        font-weight: bold;
        margin-top: 15px;
    }
    .package {
        display: inline-block;
        width: 30px;
        height: 30px;
        margin: 3px;
        border: 1px solid black;
        text-align: center;
        line-height: 30px;
        font-weight: bold;
        background-color: #ffcc99;
    }
    .truck {
        display: inline-block;
        padding: 5px;
        margin: 5px;
        border: 2px solid blue;
        font-weight: bold;
        background-color: #ccccff;
    }
    .airplane {
        display: inline-block;
        padding: 5px;
        margin: 5px;
        border: 2px solid red;
        font-weight: bold;
        background-color: #ffcccc;
    }
    .container {
        margin-top: 10px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_domain_client(domain_name):
    """Get domain and client based on selection."""
    if domain_name == "Blocksworld":
        domain = BlocksWorldDomain
    elif domain_name == "Logistics":
        domain = LogisticsDomain
    else:
        raise ValueError(f"Unknown domain: {domain_name}")
    
    # Get Azure OpenAI client
    client = get_llm_client("azure_openai")
    
    return domain, client

def visualize_blocksworld_state(state_description):
    """Visualize a blocksworld state."""
    # Parse the state description
    blocks = {}
    for part in state_description.strip("()").split(", "):
        if "on" in part:
            on_match = part.strip().split("on")
            block = on_match[0].strip()
            target = on_match[1].strip()
            blocks[block] = target
        elif "ontable" in part:
            block = part.replace("ontable", "").strip()
            blocks[block] = "table"
        # Ignore clear and handempty predicates for visualization
    
    # Build the stacks
    stacks = {}
    for block, target in blocks.items():
        if target == "table":
            if "table" not in stacks:
                stacks["table"] = []
            stacks["table"].append(block)
    
    # Process blocks on other blocks
    changes = True
    while changes:
        changes = False
        for block, target in blocks.items():
            if target != "table":
                # Find the stack containing the target
                found = False
                for base, stack in stacks.items():
                    if target in stack:
                        idx = stack.index(target)
                        stack.insert(idx + 1, block)
                        found = True
                        changes = True
                        break
                if found:
                    break
    
    # Render the stacks
    for base, stack in stacks.items():
        col = st.columns(1)[0]
        for block in stack:
            col.markdown(f'<div class="block">{block}</div>', unsafe_allow_html=True)
        col.markdown(f'<div style="width: 200px; height: 10px; background-color: brown;"></div>', unsafe_allow_html=True)

def visualize_logistics_state(state_description):
    """Visualize a logistics state."""
    # Parse the state description
    locations = {}
    trucks = {}
    airplanes = {}
    packages = {}
    
    for part in state_description.strip("()").split(", "):
        part = part.strip()
        
        # Handle package locations
        if part.startswith("at"):
            _, obj, loc = part.split()
            if obj.startswith("p"):  # Package
                packages[obj] = {"location": loc, "vehicle": None}
        
        # Handle package in vehicles
        elif part.startswith("in"):
            _, pkg, vehicle = part.split()
            packages[pkg] = {"location": None, "vehicle": vehicle}
        
        # Handle vehicle locations
        elif part.startswith("at-truck"):
            _, truck, loc = part.split()
            trucks[truck] = loc
        
        elif part.startswith("at-airplane"):
            _, plane, loc = part.split()
            airplanes[plane] = loc
    
    # Group by locations
    cities = {}
    for loc in set(list(trucks.values()) + list(airplanes.values()) + 
                  [pkg["location"] for pkg in packages.values() if pkg["location"] is not None]):
        if loc.startswith("c"):  # City
            city = loc[0:2]  # Extract city prefix (e.g., c1)
            if city not in cities:
                cities[city] = {"locations": [], "trucks": [], "airplanes": [], "packages": []}
            cities[city]["locations"].append(loc)
    
    # Add trucks to cities
    for truck, loc in trucks.items():
        city = loc[0:2]
        if city in cities:
            cities[city]["trucks"].append(truck)
    
    # Add airplanes to cities
    for plane, loc in airplanes.items():
        city = loc[0:2]
        if city in cities:
            cities[city]["airplanes"].append(plane)
    
    # Add packages to cities
    for pkg, info in packages.items():
        if info["location"] is not None:
            city = info["location"][0:2]
            if city in cities:
                cities[city]["packages"].append(pkg)
    
    # Render the cities and their locations
    cols = st.columns(len(cities))
    for i, (city, data) in enumerate(cities.items()):
        cols[i].markdown(f"<div class='subheader'>{city.upper()}</div>", unsafe_allow_html=True)
        
        for loc in sorted(data["locations"]):
            cols[i].markdown(f"<div class='location-label'>{loc}</div>", unsafe_allow_html=True)
            
            # Show trucks at this location
            trucks_at_loc = [t for t in data["trucks"] if trucks[t] == loc]
            for truck in trucks_at_loc:
                # Get packages in this truck
                packages_in_truck = [p for p, info in packages.items() if info["vehicle"] == truck]
                truck_html = f'<div class="truck">{truck}: '
                for pkg in packages_in_truck:
                    truck_html += f'<span class="package">{pkg}</span>'
                truck_html += '</div>'
                cols[i].markdown(truck_html, unsafe_allow_html=True)
            
            # Show airplanes at this location
            planes_at_loc = [a for a in data["airplanes"] if airplanes[a] == loc]
            for plane in planes_at_loc:
                # Get packages in this plane
                packages_in_plane = [p for p, info in packages.items() if info["vehicle"] == plane]
                plane_html = f'<div class="airplane">{plane}: '
                for pkg in packages_in_plane:
                    plane_html += f'<span class="package">{pkg}</span>'
                plane_html += '</div>'
                cols[i].markdown(plane_html, unsafe_allow_html=True)
            
            # Show packages at this location
            packages_at_loc = [p for p, info in packages.items() if info["location"] == loc]
            if packages_at_loc:
                pkg_html = '<div class="container">Packages: '
                for pkg in packages_at_loc:
                    pkg_html += f'<span class="package">{pkg}</span>'
                pkg_html += '</div>'
                cols[i].markdown(pkg_html, unsafe_allow_html=True)

def main():
    """Main Streamlit application."""
    st.markdown("<h1 class='main-header'>AoT+ Planning System</h1>", unsafe_allow_html=True)
    
    # Domain selection
    domain_name = st.selectbox(
        "Select Planning Domain",
        ["Blocksworld", "Logistics"]
    )
    
    # Get domain and client
    domain, client = get_domain_client(domain_name)
    
    # Get domain description
    domain_description = domain.get_domain_description()
    
    # Initialize example problem
    example_initial, example_goal, example_solution, example_random = domain.generate_example_problem()
    
    # Create AoT+ instance
    aot = AoTPlus(domain_description, "azure_openai")
    aot.llm_client = client  # Set the Azure OpenAI client
    aot.add_example(example_initial, example_goal, example_solution, example_random)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("<div class='subheader'>Initial State</div>", unsafe_allow_html=True)
        initial_state = st.text_area(
            "Initial State Description",
            example_initial,
            height=100
        )
        
        if domain_name == "Blocksworld":
            visualize_blocksworld_state(initial_state)
        elif domain_name == "Logistics":
            visualize_logistics_state(initial_state)
    
    with col2:
        st.markdown("<div class='subheader'>Goal State</div>", unsafe_allow_html=True)
        goal_state = st.text_area(
            "Goal State Description",
            example_goal,
            height=100
        )
        
        if domain_name == "Blocksworld":
            visualize_blocksworld_state(goal_state)
        elif domain_name == "Logistics":
            visualize_logistics_state(goal_state)
    
    if st.button("Plan with AoT+"):
        with st.spinner("Generating plan using AoT+ methodology with Azure OpenAI..."):
            # Solve the problem
            solution_text = aot.solve(initial_state, goal_state)
            
            # Extract plan
            plan_steps = aot.extract_plan(solution_text)
            
            # Display solution
            st.markdown("<div class='subheader'>Generated Plan</div>", unsafe_allow_html=True)
            for i, step in enumerate(plan_steps):
                st.write(f"{i+1}. {step}")
            
            # Show the raw solution
            with st.expander("Show full solution trace"):
                st.text(solution_text)

if __name__ == "__main__":
    main() 