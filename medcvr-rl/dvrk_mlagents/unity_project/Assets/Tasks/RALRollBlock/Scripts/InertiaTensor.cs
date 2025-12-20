using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class InertiaTensor : MonoBehaviour
{  
    private Rigidbody rb;
    // Start is called before the first frame update
    void Start()
    {   
        rb = GetComponent<Rigidbody>();
        Vector3 tensor;
        //This is the tensor specific for black block long scaled to PSM 20 size
        tensor = new Vector3(1.00833e-06f,1.12568e-05f,1.12568e-05f);
        // Tensor needs to be scaled back by 20
        tensor.x = rb.inertiaTensor.x/20f;
        tensor.y = rb.inertiaTensor.y/20f; 
        tensor.z = rb.inertiaTensor.z/20f;
        Debug.Log(tensor); 
        rb.inertiaTensor = tensor;
    }

    void Update()
    {
        // Debug.Log(rb.mass);
    }
}
