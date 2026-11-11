/* Read-only runtime observation bridge, compiled against Qwasm headers.
 * The engine itself is built separately, outside this repository. */
#include "quakedef.h"
#include <stdio.h>

const char *cutcontent_runtime_state(void)
{
    static char state[256];
    vec3_t position = {0, 0, 0};
    if (sv.active && sv_player)
        VectorCopy(sv_player->v.origin, position);
    snprintf(state, sizeof(state),
             "{\"loaded\":%s,\"map\":\"%s\",\"position\":[%.3f,%.3f,%.3f],"
             "\"entities\":%d,\"server_time\":%.3f}",
             sv.active && cls.signon == SIGNONS ? "true" : "false",
             sv.active ? sv.name : "", position[0], position[1], position[2],
             sv.num_edicts, sv.time);
    return state;
}
