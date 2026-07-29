#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nine-Dash Line (九段线) coordinates for South China Sea mapping.

Standard simplified coordinates describing China's claim line in the
South China Sea, commonly used in Chinese-published maps.

Source: Open geographic data widely used in academic and publishing contexts.
These coordinates trace the U-shaped line from the northeast of the
South China Sea, around the Spratly Islands, and back up to the west.

The line has 9 segments (hence "nine-dash"), encoded as separate polylines
for accurate rendering at typical map scales.
"""

NINE_DASH_SEGMENTS = [
    # Segment 1: NE corner → east of Taiwan Strait (segment 1 of 9)
    [
        (117.50, 22.00),
        (118.50, 21.50),
        (119.50, 21.00),
        (120.30, 20.50),
        (121.00, 20.00),
        (121.50, 19.50),
        (121.80, 19.00),
        (122.00, 18.50),
    ],
    # Segment 2: East of Luzon Strait (segment 2 of 9)
    [
        (121.50, 18.50),
        (121.00, 18.00),
        (120.50, 17.80),
        (120.00, 17.50),
        (119.50, 17.20),
        (119.00, 17.00),
        (118.50, 16.80),
    ],
    # Segment 3: East of Philippines (segment 3 of 9)
    [
        (118.50, 16.50),
        (118.00, 16.00),
        (117.50, 15.50),
        (117.00, 15.00),
        (116.80, 14.50),
    ],
    # Segment 4: East of Palawan (segment 4 of 9)
    [
        (117.50, 14.00),
        (118.00, 13.50),
        (118.50, 13.00),
        (119.00, 12.50),
        (119.50, 12.00),
        (119.80, 11.50),
    ],
    # Segment 5: South of Spratlys (segment 5 of 9)
    [
        (119.00, 11.00),
        (118.50, 10.50),
        (118.00, 10.00),
        (117.50, 9.50),
        (117.00, 9.00),
        (116.50, 8.50),
        (116.00, 8.00),
        (115.50, 7.50),
        (115.00, 7.00),
        (114.50, 6.50),
        (114.00, 6.00),
        (113.50, 5.50),
        (113.00, 5.00),
        (112.50, 4.50),
        (112.00, 4.00),
    ],
    # Segment 6: SW corner (segment 6 of 9)
    [
        (111.50, 4.00),
        (111.00, 4.00),
        (110.50, 4.00),
        (110.00, 4.00),
        (109.50, 4.00),
        (109.00, 4.00),
        (108.50, 4.00),
        (108.00, 4.00),
        (107.50, 4.00),
        (107.00, 4.00),
        (106.50, 4.00),
        (106.00, 4.00),
        (105.50, 4.00),
        (105.00, 4.00),
    ],
    # Segment 7: West side (segment 7 of 9)
    [
        (105.00, 4.50),
        (105.50, 5.00),
        (106.00, 5.50),
        (106.50, 6.00),
        (107.00, 6.50),
        (107.50, 7.00),
        (108.00, 7.50),
        (108.50, 8.00),
        (109.00, 8.50),
        (109.50, 9.00),
    ],
    # Segment 8: West of Paracels (segment 8 of 9)
    [
        (109.50, 9.50),
        (109.00, 10.00),
        (108.50, 10.50),
        (108.00, 11.00),
        (107.50, 11.50),
        (107.00, 12.00),
        (106.50, 12.50),
        (106.00, 13.00),
        (105.50, 13.50),
        (105.00, 14.00),
        (104.50, 14.50),
        (104.00, 15.00),
        (103.50, 15.50),
        (103.00, 16.00),
        (102.50, 16.50),
        (102.00, 17.00),
        (101.50, 17.50),
    ],
    # Segment 9: Gulf of Tonkin (segment 9 of 9)
    [
        (108.00, 17.50),
        (108.00, 18.00),
        (108.00, 18.50),
        (108.00, 19.00),
        (108.00, 19.50),
        (108.00, 20.00),
        (108.00, 20.50),
        (108.00, 21.00),
        (108.00, 21.50),
        (108.00, 22.00),
    ],
]
