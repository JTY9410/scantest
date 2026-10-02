<?php

namespace App\Support;

class EnvFile
{
    public function __construct(private readonly string $path)
    {
    }

    public static function base(): self
    {
        return new self(base_path('.env'));
    }

    public function get(string $key, ?string $default = null): ?string
    {
        return $this->all()[$key] ?? $default;
    }

    public function all(): array
    {
        if (! is_file($this->path)) {
            return [];
        }

        $values = [];
        foreach (file($this->path, FILE_IGNORE_NEW_LINES) as $line) {
            if ($line === '' || str_starts_with(ltrim($line), '#') || ! str_contains($line, '=')) {
                continue;
            }
            [$key, $value] = explode('=', $line, 2);
            $values[trim($key)] = $this->decode(trim($value));
        }

        return $values;
    }

    public function set(array $values): void
    {
        $contents = is_file($this->path) ? file_get_contents($this->path) : '';

        foreach ($values as $key => $value) {
            $line = $key.'='.$this->encode((string) $value);
            $pattern = '/^'.preg_quote((string) $key, '/').'=.*$/m';
            if (preg_match($pattern, $contents)) {
                $contents = preg_replace($pattern, $line, $contents, 1);
            } else {
                $contents = rtrim($contents)."\n".$line."\n";
            }
        }

        file_put_contents($this->path, $contents);
    }

    private function encode(string $value): string
    {
        if ($value === '' || preg_match('/[\s#"\']/', $value)) {
            return '"'.str_replace(['\\', '"'], ['\\\\', '\\"'], $value).'"';
        }

        return $value;
    }

    private function decode(string $value): string
    {
        if ($value === '') {
            return '';
        }

        $quote = $value[0];
        if (($quote === '"' || $quote === "'") && str_ends_with($value, $quote)) {
            $inner = substr($value, 1, -1);

            return $quote === '"'
                ? stripcslashes($inner)
                : str_replace(["\\'", '\\\\'], ["'", '\\'], $inner);
        }

        return $value;
    }
}
