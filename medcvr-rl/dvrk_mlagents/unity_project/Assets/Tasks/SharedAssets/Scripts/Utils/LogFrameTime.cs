using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using System.IO;

public class LogFrameTime : MonoBehaviour
{
    StreamWriter writer;
    int frame = 0;
    int avframe = 0;
    float avtime = 0;
    public MultiCutAgent agent;

    void Start()
    {
        writer = new StreamWriter("framerate.csv");
        writer.WriteLine("Frame,Time,numcut");
    }

    void Update()
    {
        // Take every 100 frames and average
        // if (frame % 10 == 0)
        // {
        //     writer.WriteLine("{0},{1},{2}", avframe, avtime / 100, agent.numRopesCut);
        //     avframe++;
        //     avtime = 0;
        // }
        // avtime += Time.deltaTime;
        // frame++;

        writer.WriteLine("{0},{1},{2}", frame, Time.deltaTime, agent.numRopesCut);
        frame++;
    }

    void OnDestroy()
    {
        writer.Flush();
        writer.Close();
    }
}
