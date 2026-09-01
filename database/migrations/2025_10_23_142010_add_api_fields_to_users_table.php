<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::table('users', function (Blueprint $table) {
            $table->string('api_key', 64)->unique()->nullable()->index()->comment('API 키');
            $table->text('api_host')->nullable()->comment('허용 IP 주소 (쉼표 구분, *는 모두 허용)');
            $table->timestamp('api_expires_at')->nullable()->comment('API 키 만료일');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::table('users', function (Blueprint $table) {
            $table->dropColumn(['api_key', 'api_host', 'api_expires_at']);
        });
    }
};
