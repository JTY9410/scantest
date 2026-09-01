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
        Schema::create('applogs', function (Blueprint $table) {
            $table->id();
            $table->datetime('timestamp', 6)->comment('타임스탬프');
            $table->foreignId('user_id')->nullable()->constrained()->cascadeOnDelete()->comment('회원 아이디');
            $table->string('type')->comment('로그 타입');
            $table->string('message', 2000)->comment('로그 메시지');
            $table->text('desc')->nullable()->comment('추가 텍스트');
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('applogs');
    }
};
