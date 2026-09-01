<?php

namespace Database\Factories;

use Illuminate\Database\Eloquent\Factories\Factory;

class CodeFactory extends Factory
{
    public function definition(): array
    {
        return [
            'type' => fake()->randomElement(['ev', 'ice']),
            'code' => fake()->unique()->regexify('[A-Z]{1}[0-9]{4}'),
            'unit_name' => fake()->word(),
            'unit_type' => fake()->word(),
            'desc' => fake()->sentence(),
            'detail_desc' => fake()->paragraph(),
            'root_cause' => fake()->paragraph(),
            'howto_fix1' => fake()->paragraph(),
            'howto_fix2' => fake()->paragraph(),
            'howto_fix3' => fake()->paragraph(),
        ];
    }
}
